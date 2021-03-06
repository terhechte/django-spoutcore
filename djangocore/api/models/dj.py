# Django dependencies.
from django.core.exceptions import FieldError
from django.db.models.query import QuerySet
from django.http import HttpResponse
from django.forms.models import modelform_factory
from django.shortcuts import get_object_or_404
from django.db.models import Q
from query_translator import translator

# Intra-app dependencies.
from djangocore.api.models.base import BaseModelResource
from djangocore.serialization import emitter, EmittableResponse

from urllib import unquote_plus

class DjangoModelResource(BaseModelResource):
    allow_related_ordering = False # Allow ordering across relationships.
    user_field_name = None # The field to filter on the current user.
                           # Only logged in users get filtered responses.

    translator = None
    
    def __init__(self, *args, **kwargs):
        super(DjangoModelResource, self).__init__(*args, **kwargs)

        """ create a translator object, so we have the regex' cached """
        self.translator = translator()

        
        # Construct a default form if we don't have one already.
        if not self.form:
            if self.fields:
                # Limit it to the specified fields, if given.
                self.form = modelform_factory(self.model, fields=self.fields)
            else:
                self.form = modelform_factory(self.model)

    def process_response(self, response, request):
        """
        Process the response and serialize any returned data structures.
        
        """
        if isinstance(response, HttpResponse):
            return response
        
        if isinstance(response, QuerySet):
            response = self.serialize_models(response)
        
        # TODO: how do we catch bad format requests?
        format = request.GET.get('format', 'json')
        response = emitter.translate(format, response)
        return response

    def process_lookups(self, lookups):
        """
        GET parameter keys are unicode strings, but we can only pass in
        strings as keyword arguments, so we convert them here.
        
        """
        return dict([(str(k), v) for k, v in lookups.items()])

    def get_query_set(self, request):
        qs = self.model._default_manager.all()
        if self.user_field_name and hasattr(request.user, 'pk'):
            lookups = {}
            lookups[self.user_field_name] = request.user
            qs = qs.filter(**lookups)
        return qs

    def length(self, request):
        lookups = request.GET.copy()

        qs = self.get_query_set(request)
        
        try:
            qs = qs.filter(**self.process_lookups(lookups))
        except FieldError, err:
            return EmittableResponse(str(err), status=400)
        
        return qs.count()

    def list(self, request):
        def iterable(obj):
            """django nowadays plants all vars in lists. 
            i.e.
            <QueryDict: {u'ordering': [u'name'], u'limit': [u'0'], u'conditions': [u'ipPublic = {ipp} AND ipUmts = {ipu}'], u'parameters': [u'ipp=192.168.1.1,ipu=frank,'], u'offset': [u'0']}>
            Thus, this function detects lists and returns the first object, if possible
            """
            if hasattr(obj, '__getitem__'):
                if len(obj)>0:
                    return obj[0]
                else:
                    return obj
            else:
                return obj

        lookups = request.GET.copy()


        qs = self.get_query_set(request)

        ordering = iterable(lookups.pop('ordering', None))
        if ordering:
            if not self.allow_related_ordering and '__' in ordering:
                return EmittableResponse("This model cannot be ordered by "
                    "related objects. Please remove all ocurrences of '__' from"
                    " your ordering parameters.", status=400)
            ordering = ordering.split(',')            
            if len(ordering) > self.max_orderings:
                return EmittableResponse("This model cannot be ordered by more "
                    "than %d parameter(s). You tried to order by %d parameters."
                    % (self.max_orderings, len(ordering)), status=400)
            qs = qs.order_by(*ordering)

        offset = int(iterable(lookups.pop('offset', 0)))
        limit = min(int(iterable(lookups.pop('limit', self.max_objects))), int(iterable(self.max_objects)))
        
        filter_q_object = None
        """ check if we have conditions and request parameters """
        conditions = iterable(lookups.pop('conditions', ""))
        if conditions!="" and conditions!=None and conditions!=0:

            """ check if we have parameters """
            parameters = iterable(lookups.pop('parameters', ""))
            if parameters=="" or parameters==None:
                parameters = {}
            else:
                """ the parameter format is 'ipp=192.168.1.1,ipu=frank,'
                we need to create dicts from that."""
                parameters = dict([x.split("=") for x in parameters.split(",") if x.strip()!=""])

            """parse the conditions """
            conditionsString = unquote_plus(conditions);

            """the format is a=b AND c=d OR """
            """ and now create a Q object from the query string """
            filter_q_object = self.translator.parse(conditionsString, parameters)
        
        try:
            # Catch any lookup errors, and return the message, since they are
            # usually quite descriptive.
            if filter_q_object:
                qs = qs.filter(filter_q_object)
            else:
                qs = qs.filter(**self.process_lookups(lookups))
        except FieldError, err:
            return EmittableResponse(str(err), status=400)
        
        return qs[offset:offset + limit]

    def show(self, request):
        pk_list = request.GET.getlist('pk')
        
        if len(pk_list) == 0:
            return EmittableResponse("The request must specify a pk argument",
                status=400)
                    
        qs = self.get_query_set(request)
        return qs.filter(pk__in=pk_list)    

    def create(self, request):
        data = request.data
        
        # Make sure the data we recieved is in the right format.
        if not isinstance(data, dict):
            return EmittableResponse("The data sent in the request was "
                "malformed", status=400)
        
        form = self.form(data)
        if form.errors:
            return EmittableResponse({'errors': form.errors}, status=400)
            
        obj = form.save()
        return self.serialize_models(obj)

    def update(self, request):
        pk_list = request.GET.getlist('pk')
        if len(pk_list) != 1:
            return EmittableResponse("The request must specify a single pk "
                "argument", status=400)
        pk = pk_list[0]
                
        # Make sure the data we recieved is in the right format.
        data = request.data
        if not isinstance(data, dict):
            return EmittableResponse("The data sent in the request was "
                "malformed", status=400)
        
        instance = get_object_or_404(self.get_query_set(request), pk=pk)

        form = self.form(data, instance=instance)
        if form.errors:
            return EmittableResponse({'errors': form.errors}, status=400)
            
        obj = form.save()
        return self.serialize_models(obj)

    def destroy(self, request):
        pk_list = request.GET.getlist('pk')
        
        if len(pk_list) == 0:
            return EmittableResponse("The request must specify a pk argument",
                status=400)
        
        qs = self.get_query_set(request)
        
        # QUESTION: Should we delete in bulk or loop through and delete?
        qs.filter(pk__in=pk_list).delete()
        
        return HttpResponse('', status=204)    

# Alias to make importing easier, while retaining the class's full name.
ModelResource = DjangoModelResource