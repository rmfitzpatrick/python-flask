import opentracing
from opentracing.ext import tags
from flask import _request_ctx_stack as stack


class FlaskTracing(opentracing.Tracer):
    """
    Tracer that can trace certain requests to a Flask app.

    @param tracer the OpenTracing tracer implementation to trace requests with
    """
    def __init__(self, tracer, trace_all_requests=False, app=None,
                 traced_attributes=[]):
        if not callable(tracer):
            self.__tracer = tracer
        else:
            self.__tracer = None
            self.__tracer_getter = tracer
        self._trace_all_requests = trace_all_requests

        # tracing all requests requires that app != None
        if self._trace_all_requests:
            @app.before_request
            def start_trace():
                self._before_request_fn(traced_attributes)

            @app.after_request
            def end_trace(response):
                self._after_request_fn(response)
                return response

    @property
    def _tracer(self):
        if not self.__tracer:
            self.__tracer = self.__tracer_getter()
        return self.__tracer

    def trace(self, *attributes):
        """
        Function decorator that traces functions

        NOTE: Must be placed after the @app.route decorator

        @param attributes any number of flask.Request attributes
        (strings) to be set as tags on the created span
        """
        def decorator(f):
            def wrapper(*args, **kwargs):
                if not self._trace_all_requests:
                    self._before_request_fn(list(attributes))
                    r = f(*args, **kwargs)
                    self._after_request_fn()
                    return r
                else:
                    return f(*args, **kwargs)
            wrapper.__name__ = f.__name__
            return wrapper
        return decorator

    def _before_request_fn(self, attributes):
        request = stack.top.request
        operation_name = request.endpoint
        headers = {}
        for k, v in request.headers:
            headers[k.lower()] = v
        span = None
        try:
            span_ctx = self._tracer.extract(opentracing.Format.HTTP_HEADERS,
                                            headers)
            scope = self._tracer.start_active_span(operation_name,
                                                   child_of=span_ctx)
        except (opentracing.InvalidCarrierException,
                opentracing.SpanContextCorruptedException):
            scope = self._tracer.start_active_span(operation_name)

        span = scope.span
        span.set_tag(tags.COMPONENT, 'Flask')
        span.set_tag(tags.HTTP_METHOD, request.method)
        span.set_tag(tags.HTTP_URL, request.base_url)
        span.set_tag(tags.SPAN_KIND, tags.SPAN_KIND_RPC_SERVER)

        for attr in attributes:
            if hasattr(request, attr):
                payload = str(getattr(request, attr))
                if payload:
                    span.set_tag(attr, payload)

    def _after_request_fn(self, response=None):
        scope = self._tracer.scope_manager.active
        if scope is not None:
            if response is not None:
                scope.span.set_tag(tags.HTTP_STATUS_CODE, response.status_code)
            scope.close()
