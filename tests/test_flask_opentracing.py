import unittest

from flask import Flask
import opentracing
from opentracing.ext import tags
from opentracing.mocktracer import MockTracer
from flask_opentracing import FlaskScopeManager, FlaskTracing


app = Flask(__name__)
test_app = app.test_client()


tracing_all = FlaskTracing(MockTracer(FlaskScopeManager()), True, app, ['url'])
tracing = FlaskTracing(MockTracer(FlaskScopeManager()))
tracing_deferred = FlaskTracing(lambda: MockTracer(FlaskScopeManager()),
                                True, app, ['url'])


@app.route('/test')
@tracing_all.trace('cookies', 'blueprint')
def check_test_works():
    return 'Success'


@app.route('/another_test')
@tracing.trace('url', 'url_rule')
def decorated_fn():
    return 'Success again'


@app.route('/another_test_simple')
@tracing.trace()
def decorated_fn_simple():
    return 'Success again'


@app.route('/wire')
def send_request():
    tracer = MockTracer()
    with tracer.start_active_span('some_span') as scope:
        span = scope.span
        # Load attributes for context injection
        span.trace_id = 1000
        span.span_id = 1001
        span.baggage = None
        headers = {}
        tracer.inject(span, opentracing.Format.TEXT_MAP, headers)
        rv = test_app.get('/test', headers=headers)
    return str(rv.status_code)


class TestTracing(unittest.TestCase):
    def setUp(self):
        tracing_all._tracer.reset()
        tracing._tracer.reset()
        tracing_deferred._tracer.reset()

    def test_span_creation(self):
        assert not tracing_all._tracer.finished_spans()
        assert not tracing._tracer.finished_spans()
        assert not tracing_deferred._tracer.finished_spans()
        test_app.get('/test')
        assert tracing_all._tracer.finished_spans()
        assert not tracing._tracer.finished_spans()
        assert tracing_deferred._tracer.finished_spans()

    def test_span_tags(self):
        test_app.get('/another_test_simple')

        spans = tracing._tracer.finished_spans()
        assert len(spans) == 1
        assert spans[0].tags == {
            tags.COMPONENT: 'Flask',
            tags.HTTP_METHOD: 'GET',
            tags.SPAN_KIND: tags.SPAN_KIND_RPC_SERVER,
            tags.HTTP_URL: 'http://localhost/another_test_simple',
        }

    def test_requests_distinct(self):
        test_app.get('/test')
        assert not tracing._tracer.finished_spans()
        assert len(tracing_all._tracer.finished_spans()) == 1
        assert len(tracing_deferred._tracer.finished_spans()) == 1

        test_app.get('/test')
        assert not tracing._tracer.finished_spans()
        assert len(tracing_all._tracer.finished_spans()) == 2
        assert len(tracing_deferred._tracer.finished_spans()) == 2
        for tracer in (tracing_all._tracer, tracing_deferred._tracer):
            span_one, span_two = tracer.finished_spans()
            assert span_one is not span_two

    def test_decorator(self):
        test_app.get('/test')
        test_app.get('/another_test')

        assert len(tracing._tracer.finished_spans()) == 1
        assert len(tracing_all._tracer.finished_spans()) == 2
        assert len(tracing_deferred._tracer.finished_spans()) == 2

        for span in tracing_all._tracer.finished_spans():
            assert 'cookies' not in span.tags
            assert 'blueprint' not in span.tags
            assert 'url' in span.tags

    def test_over_wire(self):
        rv = test_app.get('/wire')
        assert '200' in str(rv.status_code)
        spans = tracing_all._tracer.finished_spans()
        assert len(spans) == 2
        child, parent = spans
        assert child.parent_id == 1001
        assert parent.parent_id is None
