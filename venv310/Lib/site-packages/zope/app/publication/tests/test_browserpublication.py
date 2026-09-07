##############################################################################
#
# Copyright (c) 2001, 2002 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Browser Publication Tests
"""
import unittest
from io import BytesIO

from persistent import Persistent
from zope.interface import Interface
from zope.interface import implementer
from zope.principalregistry.principalregistry import principalRegistry
from zope.publisher.browser import BrowserView
from zope.publisher.browser import TestRequest
from zope.publisher.interfaces.browser import IBrowserPublisher
from zope.publisher.interfaces.browser import IDefaultBrowserLayer
from zope.publisher.publish import publish
from zope.security.checker import NamesChecker
from zope.security.checker import defineChecker
from zope.security.interfaces import ForbiddenAttribute
from zope.security.proxy import removeSecurityProxy

from zope import component
from zope.app.publication.browser import BrowserPublication
from zope.app.publication.httpfactory import HTTPPublicationRequestFactory
from zope.app.publication.tests import support
from zope.app.publication.tests.test_zopepublication import \
    BasePublicationTests as BasePublicationTests_
from zope.app.publication.traversers import TestTraverser


def foo():
    """I am an otherwise empty docstring."""
    return '<html><body>hello base fans</body></html>'


@implementer(IBrowserPublisher)
class DummyPublished:

    def publishTraverse(self, request, name):
        if name == 'bruce':
            return foo
        raise KeyError(name)

    def browserDefault(self, request):
        return self, ['bruce']


class DummyView(DummyPublished, BrowserView):

    __Security_checker__ = NamesChecker(["browserDefault", "publishTraverse"])


class BasePublicationTests(BasePublicationTests_):

    def _createRequest(self, path, publication, **kw):
        request = TestRequest(PATH_INFO=path, **kw)
        request.setPublication(publication)
        return request


class SimpleObject:
    def __init__(self, v):
        self.v = v


class I1(Interface):
    pass


@implementer(I1)
class mydict(dict):
    pass


@implementer(I1)
class O1(Persistent):
    pass


class BrowserDefaultTests(BasePublicationTests):
    """Test browser default

    many views lead to a default view
    <base href="/somepath/@@view/view_method">

    """
    klass = BrowserPublication

    def testBaseTagNoBase(self):
        self._testBaseTags('/somepath/@@view/', '')

    def testBaseTag1(self):
        self._testBaseTags('/somepath/@@view',
                           'http://127.0.0.1/somepath/@@view/bruce')

    def testBaseTag2(self):
        self._testBaseTags('/somepath/',
                           'http://127.0.0.1/somepath/@@view/bruce')

    def testBaseTag3(self):
        self._testBaseTags('/somepath',
                           'http://127.0.0.1/somepath/@@view/bruce')

    def _testBaseTags(self, url, expected):
        # Make sure I1 and O1 are visible in the module namespace
        # so that the classes can be pickled.
        import transaction

        pub = BrowserPublication(self.db)

        component.provideAdapter(DummyView, (I1, IDefaultBrowserLayer),
                                 Interface, name='view')

        support.setDefaultViewName(I1, 'view')
        component.provideAdapter(TestTraverser, (None, IDefaultBrowserLayer),
                                 IBrowserPublisher)

        ob = O1()

        # the following is for running the tests standalone
        principalRegistry.defineDefaultPrincipal(
            'tim', 'timbot', 'ai at its best')

        # now place our object inside the application

        connection = self.db.open()
        app = connection.root()['Application']
        app.somepath = ob
        transaction.commit()
        connection.close()

        defineChecker(app.__class__, NamesChecker(somepath='xxx'))

        req = self._createRequest(url, pub)
        response = req.response

        publish(req, handle_errors=0)

        self.assertEqual(response.getBase(), expected)

    def _createRequest(self, path, publication, **kw):
        request = TestRequest(PATH_INFO=path, **kw)
        request.setPublication(publication)
        return request


class BrowserPublicationTests(BasePublicationTests):

    klass = BrowserPublication

    def testAdaptedTraverseNameWrapping(self):

        @implementer(IBrowserPublisher)
        class Adapter:
            def __init__(self, context, request):
                self.context = context
                self.counter = 0

            def publishTraverse(self, request, name):
                self.counter += 1
                return self.context[name]

        component.provideAdapter(Adapter, (I1, IDefaultBrowserLayer),
                                 IBrowserPublisher)

        ob = mydict()
        ob['bruce'] = SimpleObject('bruce')
        ob['bruce2'] = SimpleObject('bruce2')
        pub = self.klass(self.db)
        ob2 = pub.traverseName(self._createRequest('/bruce', pub), ob, 'bruce')
        self.assertRaises(ForbiddenAttribute, getattr, ob2, 'v')
        self.assertEqual(removeSecurityProxy(ob2).v, 'bruce')

    def testAdaptedTraverseDefaultWrapping(self):
        # Test default content and make sure that it's wrapped.
        @implementer(IBrowserPublisher)
        class Adapter:
            def __init__(self, context, request):
                self.context = context

            def browserDefault(self, request):
                return (self.context['bruce'], 'dummy')

        component.provideAdapter(Adapter,
                                 (I1, IDefaultBrowserLayer),
                                 IBrowserPublisher)

        ob = mydict()
        ob['bruce'] = SimpleObject('bruce')
        ob['bruce2'] = SimpleObject('bruce2')
        pub = self.klass(self.db)
        ob2, x = pub.getDefaultTraversal(
            self._createRequest('/bruce', pub), ob)
        self.assertEqual(x, 'dummy')
        self.assertRaises(ForbiddenAttribute, getattr, ob2, 'v')
        self.assertEqual(removeSecurityProxy(ob2).v, 'bruce')

    def testTraverseName(self):
        pub = self.klass(self.db)

        class C:
            x = SimpleObject(1)
        ob = C()
        r = self._createRequest('/x', pub)
        component.provideAdapter(TestTraverser,
                                 (None, IDefaultBrowserLayer),
                                 IBrowserPublisher)
        ob2 = pub.traverseName(r, ob, 'x')
        self.assertRaises(ForbiddenAttribute, getattr, ob2, 'v')
        self.assertEqual(removeSecurityProxy(ob2).v, 1)
        self.assertIs(pub.traverseName(r, ob, '.'), ob)

    def testTraverseNameView(self):
        pub = self.klass(self.db)

        class ExampleInterface(Interface):
            pass

        @implementer(ExampleInterface)
        class C:
            pass
        ob = C()

        class V:
            def __init__(self, context, request):
                pass
        r = self._createRequest('/@@spam', pub)
        component.provideAdapter(
            V, (ExampleInterface, IDefaultBrowserLayer), Interface, name='spam'
        )
        ob2 = pub.traverseName(r, ob, '@@spam')
        self.assertEqual(ob2.__class__, V)

    def testTraverseNameSiteManager(self):
        pub = self.klass(self.db)

        class C:
            def getSiteManager(self):
                return SimpleObject(1)
        ob = C()
        r = self._createRequest('/++etc++site', pub)
        ob2 = pub.traverseName(r, ob, '++etc++site')
        self.assertRaises(ForbiddenAttribute, getattr, ob2, 'v')
        self.assertEqual(removeSecurityProxy(ob2).v, 1)

    def testTraverseNameApplicationControl(self):
        from zope.applicationcontrol.applicationcontrol import \
            applicationController
        from zope.applicationcontrol.applicationcontrol import \
            applicationControllerRoot
        from zope.traversing.interfaces import IEtcNamespace
        component.provideUtility(applicationController,
                                 IEtcNamespace, name='process')

        pub = self.klass(self.db)
        r = self._createRequest('/++etc++process', pub)
        ac = pub.traverseName(r,
                              applicationControllerRoot,
                              '++etc++process')
        self.assertEqual(ac, applicationController)
        r = self._createRequest('/++etc++process', pub)
        app = r.publication.getApplication(r)
        self.assertEqual(app, applicationControllerRoot)

    def testHEADFuxup(self):
        pub = self.klass(None)

        class User:
            id = 'bob'

        # With a normal request, we should get a body:
        request = TestRequest(BytesIO(b''), {'PATH_INFO': '/'})
        request.setPrincipal(User())
        request.response.setResult("spam")
        pub.afterCall(request, None)
        self.assertEqual(request.response.consumeBody(), b'spam')

        # But with a HEAD request, the body should be empty
        request = TestRequest(BytesIO(b''), {'PATH_INFO': '/'})
        request.setPrincipal(User())
        request.method = 'HEAD'
        request.response.setResult("spam")
        pub.afterCall(request, None)
        self.assertEqual(request.response.consumeBody(), b'')

    def testUnicode_NO_HTTP_CHARSET(self):
        # Test so that a unicode body doesn't cause a UnicodeEncodeError
        request = TestRequest(BytesIO(b''), {})
        request.response.setResult("\u0442\u0435\u0441\u0442")
        headers = request.response.getHeaders()
        headers.sort()
        self.assertEqual(
            headers,
            [('Content-Length', '8'),
             ('Content-Type', 'text/plain;charset=utf-8'),
             ('X-Content-Type-Warning', 'guessed from content'),
             ('X-Powered-By', 'Zope (www.zope.org), Python (www.python.org)')])
        self.assertEqual(
            request.response.consumeBody(),
            b'\xd1\x82\xd0\xb5\xd1\x81\xd1\x82')


class HTTPPublicationRequestFactoryTests(BasePublicationTests):

    def setUp(self):
        super(BasePublicationTests, self).setUp()
        from zope.app.publication.requestpublicationfactories import \
            BrowserFactory
        from zope.app.publication.requestpublicationfactories import \
            HTTPFactory
        from zope.app.publication.requestpublicationfactories import \
            SOAPFactory
        from zope.app.publication.requestpublicationfactories import \
            XMLRPCFactory
        from zope.app.publication.requestpublicationregistry import \
            factoryRegistry

        factoryRegistry.register('*', '*', 'HTTP', 0, HTTPFactory())
        factoryRegistry.register('POST', 'text/xml', 'SOAP', 20, SOAPFactory())
        factoryRegistry.register('POST', 'text/xml', 'XMLRPC', 10,
                                 XMLRPCFactory())
        factoryRegistry.register('GET', '*', 'BROWSER', 10, BrowserFactory())
        factoryRegistry.register('POST', '*', 'BROWSER', 10, BrowserFactory())
        factoryRegistry.register('HEAD', '*', 'BROWSER', 10, BrowserFactory())

    def testGetBackSamePublication(self):
        factory = HTTPPublicationRequestFactory(db=None)
        args = (BytesIO(b''), {})
        self.assertEqual(
            id(factory(*args).publication),
            id(factory(*args).publication))


def test_suite():
    loadTestsFromTestCase = unittest.defaultTestLoader.loadTestsFromTestCase
    return unittest.TestSuite((
        loadTestsFromTestCase(BrowserPublicationTests),
        loadTestsFromTestCase(BrowserDefaultTests),
        loadTestsFromTestCase(HTTPPublicationRequestFactoryTests),
    ))
