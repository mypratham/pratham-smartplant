##############################################################################
#
# Copyright (c) 2011 Zope Foundation and Contributors.
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

from unittest import TestCase

from zope.browser.interfaces import ISystemErrorView
from zope.component import getMultiAdapter
from zope.component import provideAdapter
from zope.component.testlayer import ZCMLFileLayer
from zope.interface import Interface
from zope.publisher.defaultview import getDefaultViewName
from zope.publisher.http import HTTPRequest
from zope.publisher.interfaces import NotFound
from zope.publisher.interfaces import TraversalException
from zope.publisher.interfaces.http import IHTTPException
from zope.publisher.interfaces.http import IHTTPRequest
from zope.publisher.interfaces.http import IMethodNotAllowed
from zope.publisher.interfaces.http import MethodNotAllowed
from zope.security.interfaces import Unauthorized

import zope.errorview
from zope.errorview import http


class TestErrorViews(TestCase):

    def setUp(self):
        self.request = HTTPRequest('', {})

    def test_exceptionviewbase(self):
        view = http.ExceptionViewBase(Exception(), self.request)
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(str(view), '')
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 500)

    def test_exceptionview(self):
        view = http.ExceptionView(Exception(), self.request)
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(str(view), '')
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 500)

    def test_systemerrormixin_view(self):
        class SystemErrorView(http.ExceptionViewBase,
                              http.SystemErrorViewMixin):
            pass
        view = SystemErrorView(Exception(), self.request)
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertTrue(ISystemErrorView.providedBy(view))
        self.assertTrue(view.isSystemError())
        self.assertEqual(str(view), '')
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 500)

    def test_traversalexceptionview(self):
        view = http.TraversalExceptionView(TraversalException(), self.request)
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 404)

        self.request = HTTPRequest('', {'REQUEST_METHOD': 'MKCOL'})
        view = http.TraversalExceptionView(TraversalException(), self.request)
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 404)

        self.request.setTraversalStack(['foo', 'bar'])
        view = http.TraversalExceptionView(TraversalException(), self.request)
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 409)

    def test_unauthorizedexceptionview(self):
        view = http.UnauthorizedView(Unauthorized(), self.request)
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 401)
        self.assertTrue(
            self.request.response.getHeader(
                'WWW-Authenticate', '', True).startswith('basic'))

    def test_methodnotallowedview(self):
        error = MethodNotAllowed(object(), self.request)
        view = http.MethodNotAllowedView(error, self.request)
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 405)
        self.assertEqual(self.request.response.getHeader('Allow'), '')

        class MyMethodNotAllowedView(http.MethodNotAllowedView):
            def allowed(self):
                return 'GET', 'POST', 'PUT', 'DELETE'

        MyMethodNotAllowedView(error, self.request)()
        self.assertEqual(self.request.response.getStatus(), 405)
        self.assertEqual(
            self.request.response.getHeader('Allow'), 'GET, POST, PUT, DELETE')


http_layer = ZCMLFileLayer(zope.errorview, zcml_file='http.zcml')


class TestErrorViewsFunctional(TestCase):

    layer = http_layer

    def setUp(self):
        self.request = HTTPRequest('', {})

    def test_defaultname(self):
        self.assertEqual(
            getDefaultViewName(Exception(), self.request), 'index.html')
        self.assertEqual(
            getDefaultViewName(
                TraversalException(), self.request), 'index.html')
        self.assertEqual(
            getDefaultViewName(
                Unauthorized(), self.request), 'index.html')
        error = MethodNotAllowed(object(), self.request)
        self.assertEqual(
            getDefaultViewName(error, self.request), 'index.html')

    def test_exceptionview(self):
        view = getMultiAdapter((Exception(), self.request), name='index.html')
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 500)

    def test_traversalexceptionview(self):
        view = getMultiAdapter(
            (TraversalException(), self.request), name='index.html')
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 404)
        # XXX test the MKCOL verb here too.

    def test_notfound(self):
        view = getMultiAdapter((NotFound(object(), self.request),
                                self.request),
                               name='index.html')
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 404)

    def test_unauthorizedexceptionview(self):
        view = getMultiAdapter(
            (Unauthorized(), self.request), name='index.html')
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 401)
        self.assertTrue(
            self.request.response.getHeader(
                'WWW-Authenticate', '', True).startswith('basic'))

    def test_methodnotallowedview(self):
        error = MethodNotAllowed(object(), self.request)
        view = getMultiAdapter((error, self.request), name='index.html')
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 405)
        self.assertEqual(self.request.response.getHeader('Allow'), '')

        class MyMethodNotAllowedView(http.MethodNotAllowedView):
            def allowed(self):
                return 'GET', 'POST', 'PUT', 'DELETE'

        provideAdapter(
            MyMethodNotAllowedView,
            (IMethodNotAllowed, IHTTPRequest), Interface, 'index.html')

        view = getMultiAdapter((error, self.request), name='index.html')()
        self.assertEqual(self.request.response.getStatus(), 405)
        self.assertEqual(
            self.request.response.getHeader('Allow'), 'GET, POST, PUT, DELETE')
