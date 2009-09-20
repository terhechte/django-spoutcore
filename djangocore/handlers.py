from django.db import IntegrityError
from django.db.models.fields import FieldDoesNotExist

from django.forms import model_to_dict
from django.forms.models import modelform_factory
from django.conf import settings
from django.http import HttpResponse

from piston.handler import BaseHandler
 
from djangocore.utils import EmitterHttpResponse
from djangocore.decorators import staff_member_required, permission_required, \
  get_model_from_kwargs, get_emitter_format

__all__ = ['LengthHandler', 'RangeHandler', 'BulkHandler', 'ObjectHandler']

class LengthHandler(BaseHandler):
    allowed_methods = ('GET',)

    @staff_member_required
    @permission_required('%(app_label)s.change_%(module_name)s')
    @get_model_from_kwargs
    def read(self, request, model):
        return model._default_manager.count()

class RangeHandler(BaseHandler):
    """
    Returns a range of objects ordered by a given set of fields. Returns
    no more than settings.MAX_OBJECTS_PER_REQUEST number objects. If
    more than the maximum are ohasked for, a 400 Bad Request will be
    returned.
    
    MAX_OBJECTS_PER_REQUEST defaults to 300 if not specified.
    
    GET Parameters::
        
        ordering: A comma-separated string of field names to order on.
        Field names starting with a hyphen (-) will be sorted in
        descending order.
        
        start: An integer, specifying the (0-based) index of where to
        start the range.
        
        end: An integer, specifying the (0-based) index of where to end
        the range.
    """

    allowed_methods = ('GET',)

    @staff_member_required
    @permission_required('%(app_label)s.change_%(module_name)s')
    @get_model_from_kwargs
    @get_emitter_format
    def read(self, request, model, emitter_format):
        max_objects_per_request = getattr(settings, \
          'SPROUTCORE_MAX_OBJECTS_PER_REQUEST', 300)

        ordering = request.GET.get('ordering', 'pk').split(',')
        start = int(request.GET.get('start', 0))
        end = int(request.GET.get('end', max_objects_per_request))

        # Client asked for too many objects! Bad client! Bad client!
        if end - start > max_objects_per_request:
            ret = {'message': "Requests may not specify more than %d records " \
              "to return (asked for %d)." % (max_objects_per_request, \
              end - start)}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp

        return model._default_manager.values().order_by(*ordering)[start:end]

class BulkHandler(BaseHandler):
    allowed_methods = ('GET', 'PUT', 'DELETE')
    
    @staff_member_required
    @permission_required('%(app_label)s.change_%(module_name)s')
    @get_model_from_kwargs
    @get_emitter_format
    def read(self, request, model, emitter_format):
        pk_list = request.GET.getlist('pk')
        if len(pk_list) == 0:
            ret = {'message': "Requests must specify at least one pk argument" \
              " in the query paramters (%d given)." % len(pk)}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp

        max_objects_per_request = getattr(settings, \
          'SPROUTCORE_MAX_OBJECTS_PER_REQUEST', 300)

        # Client asked for too many objects! Bad client! Bad client!
        if len(pk_list) > max_objects_per_request:
            ret = {'message': "Requests may not specify more than %d records " \
              "to return (asked for %d)." % (max_objects_per_request, \
              len(pk_list))}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp
        
        return model._default_manager.values().filter(pk__in=pk_list)
        
    @staff_member_required
    @permission_required('%(app_label)s.change_%(module_name)s')
    @get_model_from_kwargs
    @get_emitter_format
    def update(self, request, model, emitter_format):
        pk_list = request.GET.getlist('pk')
        if len(pk_list) == 0:
            ret = {'message': "Requests must specify at least one pk argument" \
              " in the query paramters (%d given)." % len(pk)}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp

        # Make sure the PUT data doesn't contain the primary key for a model. If
        # it does, you'll throw an IntegrityError if there is another object
        # with the same pk, since pks must be unique. To make things easy, we go
        # ahead and remove the primary key field from the input automatically.
        attrs = request.PUT
        attrs.pop(model._meta.pk.name, None)
        
        try:
            objects = model._default_manager.filter(pk__in=pk_list)
            objects.update(**attrs)
        except FieldDoesNotExist, error:
            ret = {'message': "Request specified a non-existent field to " \
              "update: %s" % error}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp
        except (ValueError, TypeError, IntegrityError), error:
            ret = {'message': "Request specified inappropriate data for a " \
              "field: %s" % msg}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp
        
        return objects.values()
        
    @staff_member_required
    @permission_required('%(app_label)s.delete_%(module_name)s')
    @get_model_from_kwargs
    @get_emitter_format
    def delete(self, request, model, emitter_format):
        pk_list = request.GET.getlist('pk')
        if len(pk_list) == 0:
            ret = {'message': "Requests must specify at least one pk argument" \
              " in the query paramters (%d given)." % len(pk)}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp
        model._default_manager.filter(pk__in=pk_list).delete()

        # Successful delete requests, return an emtpy body, as per RFC2616
        return HttpResponse('', mimetype='text/plain; charset=utf-8', \
          status=204)

class ObjectHandler(BaseHandler):
    allowed_methods = ('GET', 'POST', 'PUT', 'DELETE')

    @staff_member_required
    @permission_required('%(app_label)s.change_%(module_name)s')
    @get_model_from_kwargs
    @get_emitter_format
    def read(self, request, model, emitter_format):
        pk = request.GET.getlist('pk')
        if len(pk) != 1:
            ret = {'message': "Requests must specify exactly one pk argument " \
              "in the query paramters (%d given)." % len(pk)}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp
        return model._default_manager.values().get(pk__in=pk)
    
    @staff_member_required
    @permission_required('%(app_label)s.add_%(module_name)s')
    @get_model_from_kwargs
    @get_emitter_format
    def create(self, request, model, emitter_format):
        ModelForm = modelform_factory(model)
        form = ModelForm(request.POST)
        if form.errors:
            ret = {'message': "The submitted data contained %s errors." % \
              len(form.errors), 'errors': form.errors}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp

        obj = form.save()
        return model_to_dict(obj)
    
    @staff_member_required
    @permission_required('%(app_label)s.change_%(module_name)s')
    @get_model_from_kwargs
    @get_emitter_format
    def update(self, request, model, emitter_format):
        """
        PUT will attempt to update as many existing objects as it can find
        in the database. If an object with the specified pk doesn't exist,
        it won't be created. Only successfully updated objects are returned.
        
        It is only necessary to send (attribute: value) pairs for attributes
        you wish to change. Any unspecified attributes will retain their
        previous values on the object. This means you can send a list of
        hashes, each with only a pk and one other value, which in turn, 
        means it is very simple to do bulk update operations.
        """
        pk = request.GET.getlist('pk')
        if len(pk) != 1:
            ret = {'message': "Requests must specify exactly one pk argument " \
              "in the query paramters (%d given)." % len(pk)}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp

        try:
            obj = model._default_manager.values().get(pk__in=pk)
        except model.DoesNotExist, msg:
            ret = {'message': "No object with the given pk exists (asked for " \
              "pk %s)." % pk[0]}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp

        ModelForm = modelform_factory(model)
        form = ModelForm(request.POST, instance=obj)
        if form.errors:
            ret = {'message': "The submitted data contained %s errors." % \
              len(form.errors), 'errors': form.errors}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp

        obj = form.save()
        return model_to_dict(obj)

    @staff_member_required
    @permission_required('%(app_label)s.delete_%(module_name)s')
    @get_model_from_kwargs
    @get_emitter_format
    def delete(self, request, model, emitter_format):
        # Call getlist on GET to make sure that the client didn't try to send
        # more than one pk in the request. If they did, then we can return an
        # Http 400 Bad Request, since this method only deletes a single object.
        # If we only called get() on GET, then we'd only be deleting the last
        # pk sent in the query string, completely ignoring any others.
        pk = request.GET.getlist('pk')
        if len(pk) != 1:
            ret = {'message': "Requests must specify exactly one pk argument " \
              "in the query paramters (%d given)." % len(pk)}
            resp = EmitterHttpResponse(request, self, ret, \
              status=400, format=emitter_format)
            return resp
        model._default_manager.get(pk__in=pk).delete()

        # Successful delete requests, return an emtpy body, as per RFC2616
        return HttpResponse('', mimetype='text/plain; charset=utf-8', \
          status=204)
