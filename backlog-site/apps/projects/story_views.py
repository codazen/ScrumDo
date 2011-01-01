from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.http import HttpResponseRedirect, HttpResponseForbidden
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.utils.datastructures import SortedDict
from django.utils.translation import ugettext_lazy as _
from django.http import HttpResponse
from django.core import serializers

from xlrd import open_workbook

from django.conf import settings

import re

if "notification" in settings.INSTALLED_APPS:
    from notification import models as notification
else:
    notification = None

from projects.models import Project, ProjectMember, Iteration, Story
from projects.forms import *
from projects.access import *
import projects.signals as signals


# View called via ajax on the iteration or iteration planning pages.  Meant to set the status of 
# a story, and then return an html snippet that can be replaced on the page with the new status
@login_required
def set_story_status( request, group_slug, story_id, status):
  story = get_object_or_404( Story, id=story_id )
  write_access_or_403(story.project,request.user)
  story.status = status;
  story.save();         
  signals.story_status_changed.send( sender=request, story=story, user=request.user )
  if( request.POST.get("return_type","mini") == "mini"):
    return render_to_response("stories/single_mini_story.html", {
        "story": story,
      }, context_instance=RequestContext(request))
  return render_to_response("stories/single_block_story.html", {
      "story": story,
    }, context_instance=RequestContext(request))


# Deletes a story.  No further confirmation, don't post here if you want your story.
# We're doing some confirmation client-side.  Sometimes called via ajax, sometimes
# a normal request.  If a normal request, there should be a GET param specifying where
# to send us to next.
@login_required
def delete_story( request, group_slug, story_id ):
  if request.method == "POST":
    story = get_object_or_404( Story, id=story_id )  
    write_access_or_403(story.project,request.user)
    signals.story_deleted.send( sender=request, story=story, user=request.user )
    story.sync_queue.clear()
    story.delete()            
    
    redirTo = request.GET.get("redirectTo", "")
    if redirTo:
      return HttpResponseRedirect(redirTo );
    else:
      return HttpResponse("OK");
  else:
    return HttpResponse("FAIL");
     
# This is the request handler that gets called from the story_list and iteraqtion pages when the user drags & drops a story to a
# new ranking or a new iteration.  It should have two post variables, index and iteration
@login_required
def reorder_story( request, group_slug, story_id):
  story = get_object_or_404( Story, id=story_id )
  project = get_object_or_404( Project, slug=group_slug )
  write_access_or_403(project,request.user)
  if request.method == 'POST':
    rank = 0      
    target_iteration = request.POST["iteration"]
    iteration = get_object_or_404( Iteration, id=target_iteration )
    
    if request.POST.get("action","") == "reorder" :
      # Sometimes, we're just moving iterations...
      target_rank = int(request.POST["index"])
      story.rank = target_rank;    
      
    story.iteration = iteration;
    story.save()
    
    stories = project.stories.all().filter(iteration=iteration).order_by("rank")
    
    if request.POST.get("action","") == "reorder" :
      # For now, a stupid reorder everything algorithm
      for otherStory in stories:
        if rank == target_rank:
          rank+=1
        
        if otherStory != story:        
          otherStory.rank = rank
          otherStory.save()      
          rank = rank + 1
        
    return HttpResponse("OK")
  return  HttpResponse("Fail")
  

# On the iteration planning page, this renders one story view.  Generally called
# via ajax.
@login_required
def mini_story( request, group_slug, story_id):
  story = get_object_or_404( Story, id=story_id )
  read_access_or_403(story.project,request.user)
  return render_to_response("stories/single_mini_story.html", {
      "story": story,
    }, context_instance=RequestContext(request))


# calculates the rank a new story should have for a project based off of 3 general rankings.
# 0=top, 1=middle, 2=bottom
def calculate_rank( project, general_rank ):
  if( general_rank == 0):
    return 0 
  if( general_rank == 1):
    return round( project.stories.all().count() / 2)
  return project.stories.all().count()+1


# Returns the edit-story form, with minimal html wrapper.  This is useful for displaying within
# a facebox popup.  
# One place it's used is on the iteration page when you click the magnifying glass for a story.
@login_required
def story( request, group_slug, story_id ):
  story = get_object_or_404( Story, id=story_id )
  project = get_object_or_404( Project, slug=group_slug )
  return_type = request.GET.get("return_type","mini")

  if request.method == 'POST': # If the form has been submitted...
    write_access_or_403(project,request.user)
    form = StoryForm( project, request.POST, project, instance=story) # A form bound to the POST data    

    if form.is_valid(): # All validation rules pass      
      story = form.save(  )      
      signals.story_updated.send( sender=request, story=story, user=request.user )

    if( request.POST['return_type'] == 'mini'):
      return render_to_response("stories/single_mini_story.html", {
          "story": story,         
        }, context_instance=RequestContext(request))
    if( request.POST['return_type'] == 'block'):
      return render_to_response("stories/single_block_story.html", {
          "story": story,         
        }, context_instance=RequestContext(request))
  
  else:
    read_access_or_403(project,request.user)
    form = StoryForm(project, instance=story )
  
  return   render_to_response("stories/story.html", {
      "story": story,
      "form": form,
      "project": project,
      "return_type": return_type
    }, context_instance=RequestContext(request))

# Returns the stories for a given iteration as an html snippet.  The iteration planning page uses this
# uplon load, and then also upon filtering by the user
@login_required
def stories_iteration(request, group_slug, iteration_id):
  project = get_object_or_404(Project, slug=group_slug)  
  read_access_or_403(project,request.user)
  iteration = get_object_or_404(Iteration, id=iteration_id, project=project)  
  
  order_by = request.GET.get("order_by","rank");
  display_type = request.GET.get("display_type","mini")
  text_search = request.GET.get("search","")
  tags_search = request.GET.get("tags","")

  tags_list = re.split('[, ]+', tags_search)

  # There's probably a better way to set up these filters...
  if text_search and tags_search:
    stories = iteration.stories.filter(story_tags__tag__name__in=tags_list).extra( where = ["MATCH(summary, detail, extra_1, extra_2, extra_3) AGAINST (%s IN BOOLEAN MODE)"], params=[text_search]).distinct()
  elif tags_search:
    stories = iteration.stories.filter(story_tags__tag__name__in=tags_list).distinct().order_by(order_by)
  elif text_search:
    stories = iteration.stories.extra( where = ["MATCH(summary, detail, extra_1, extra_2, extra_3) AGAINST (%s IN BOOLEAN MODE)"], params=[text_search]).order_by(order_by)
  else:
    stories = iteration.stories.order_by(order_by)

  return render_to_response("stories/mini_story_list.html", {
    "stories": stories,
    "project":project,
    "display_type": display_type
  }, context_instance=RequestContext(request))


# The iteration planning tool.  It can also handle the add story form.
# TODO (cleanup): We should factor out the add story form functionality
# TODO (cleanup): We should rename this method, and likely rename the URL that points at it as well.
@login_required
def stories(request, group_slug):
  project = get_object_or_404(Project, slug=group_slug)  
  write_access_or_403(project,request.user)
  if request.method == 'POST': # If the form has been submitted...
    
    form = StoryForm(project, request.POST) # A form bound to the POST data
    if form.is_valid(): # All validation rules pass
      story = form.save( commit=False )
      story.local_id = project.getNextId()
      story.project = project
      story.creator = request.user
      story.iteration = project.get_default_iteration()
      story.rank = calculate_rank( project, int(form.cleaned_data['general_rank']) )
      story.save()             
      signals.story_created.send( sender=request, story=story, user=request.user )
      request.user.message_set.create(message="New story created.")
      form = StoryForm(project)
  else:
    form = StoryForm(project)

  return render_to_response("stories/story_list.html", {
    "add_story_form": form,
    "project": project,
    "default_iteration_id": int(request.GET.get("iteration","-1"))

  }, context_instance=RequestContext(request))




# Handles the excel import.
@login_required
def import_file(request, group_slug):
  project = get_object_or_404(Project, slug=group_slug)
  write_access_or_403(project,request.user)
  if request.method == 'POST':     
      processImport(project, request.FILES['import_file'], request.user);
      return HttpResponseRedirect(reverse('project_detail', kwargs={'group_slug':project.slug}) )
  else:
      form = ImportForm()
      
  return render_to_response("projects/import.html", {
           "form":form,
        }, context_instance=RequestContext(request))


def processImport( project, file , user):
  workbook = open_workbook(file_contents=file.read())
  sheet = workbook.sheets()[0];
  count = 0
  for row in range(sheet.nrows-1):    
    summary = sheet.cell(row+1,0).value
    detail = sheet.cell(row+1,1).value
    count = count + 1
    try:
      points = int(sheet.cell(row+1,2).value)
    except:
      points = "?"
    story = Story( project=project, summary=summary, detail=detail, rank=0, local_id=project.stories.count()+1, creator=user, points=points, iteration=project.get_default_iteration())
    story.save()   
    signals.story_created.send( sender=request, story=story, user=user )
  user.message_set.create(message=("%d stories imported" % count))

def pretty_print_story(request, group_slug, story_id):
  """Returns an html snippet that we use for a read-only full view of the story.  Right now, this is used
     when you mouse-hover over the eye icon for a story on an iteration page.  """
  story = get_object_or_404(Story, id=story_id)  
  read_access_or_403( story.project, request.user )

  return render_to_response("stories/single_story_read_only.html", {      
      "story": story      
  }, context_instance=RequestContext(request))