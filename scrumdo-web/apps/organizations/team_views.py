# ScrumDo - Agile/Scrum story management web application 
# Copyright (C) 2011 ScrumDo LLC
# 
# This software is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
# 
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
# 
# You should have received a copy (See file COPYING) of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.http import HttpResponseRedirect, HttpResponseForbidden
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.utils.translation import ugettext_lazy as _
from django.http import HttpResponse
from django.core import serializers
from django.conf import settings

from organizations.forms import *
from organizations.models import *
from organizations.team_models import *

from organizations.forms import AddUserForm

def team(request, organization_slug, team_id):
  organization  = get_object_or_404(Organization, slug=organization_slug)
  team = get_object_or_404(Team, id=team_id)
  adduser_form=AddUserForm(team=team)
  
  if request.method == "POST":
    if not _isAdmin(request.user, organization):
      return HttpResponseForbidden("Can not complete action - You are not an admin on this team")
    action = request.POST.get("action")
    if action == "addMember":
      adduser_form = AddUserForm(request.POST, team=team)
      if adduser_form.is_valid():
        adduser_form.save(request.user)
        request.user.message_set.create(message="Member added to team.")               
        adduser_form=AddUserForm(team=team)
    if action == "addProject":
      project = get_object_or_404( Project, id=request.POST.get("project") )
      team.projects.add(project)
      team.save()
    if action == "removeProject":
      project = Project.objects.filter(id=request.POST.get("project_id"))[0]
      team.projects.remove(project)
      team.save()
    if action == "removeUser":
      user = User.objects.filter(id=request.POST.get("user_id"))[0]
      if user == request.user and team.access_type=="admin":
        request.user.message_set.create(message="Can't remove yourself from the team admin group.")               
      else:
        team.members.remove(user);
        team.save()
  
  return render_to_response("organizations/team.html", {    
      "organization": organization,
      "team": team,
      "adduser_form":adduser_form
    }, context_instance=RequestContext(request))
  
  
  
  
def _isAdmin( user, organization ):
  return Organization.objects.filter( teams__members = user , teams__access_type="admin", teams__organization=organization).count() > 0
  
def team_create(request, organization_slug):
  organization = get_object_or_404(Organization, slug=organization_slug)
  
  if request.method == 'POST': # If the form has been submitted...
    form = TeamForm( request.POST)
    if form.is_valid(): # All validation rules pass      
      team = form.save( commit=False )
      team.organization = organization
      team.save()

      request.user.message_set.create(message="Team Created.")               
      return HttpResponseRedirect(reverse("organization_detail",  kwargs={'organization_slug':organization.slug}))
  else:
    form = TeamForm()
  


  return render_to_response("organizations/create_team.html", {    
      "form": form
    }, context_instance=RequestContext(request))