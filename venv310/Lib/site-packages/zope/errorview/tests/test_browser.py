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

from zope.authentication.interfaces import IAuthentication
from zope.component import getMultiAdapter
from zope.component import getUtility
from zope.component.testlayer import ZCMLFileLayer
from zope.interface import implementer
from zope.publisher.browser import TestRequest
from zope.publisher.defaultview import getDefaultViewName
from zope.publisher.interfaces import NotFound
from zope.publisher.interfaces.http import IHTTPException
from zope.security.interfaces import Unauthorized

import zope.errorview


browser_layer = ZCMLFileLayer(zope.errorview.tests)


class MockPrincipal:
    id = 'mock principal'


@implementer(IAuthentication)  # this is a lie.
class MockAuthenticationUtility:

    status = None

    def unauthorized(self, principal_id, request):
        if self.status is not None:
            request.response.setStatus(self.status)


class TestErrorViews(TestCase):

    layer = browser_layer

    def setUp(self):
        self.request = TestRequest()

    def test_defaultname(self):
        self.assertEqual(
            getDefaultViewName(Exception(), self.request), 'index.html')
        error = NotFound(object(), self.request)
        self.assertEqual(
            getDefaultViewName(error, self.request), 'index.html')
        self.assertEqual(
            getDefaultViewName(
                Unauthorized(), self.request), 'index.html')

    def test_exceptionview(self):
        view = getMultiAdapter((Exception(), self.request), name='index.html')
        self.assertEqual(view(), 'A system error occurred.')
        self.assertEqual(self.request.response.getStatus(), 500)

    def test_notfoundview(self):
        error = NotFound(object(), self.request)
        view = getMultiAdapter((error, self.request), name='index.html')
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(view(), 'The requested resource can not be found.')
        self.assertEqual(self.request.response.getStatus(), 404)

    def test_unauthorizedview(self):
        self.request.setPrincipal(MockPrincipal())
        view = getMultiAdapter(
            (Unauthorized(), self.request), name='index.html')
        self.assertTrue(IHTTPException.providedBy(view))
        self.assertEqual(
            view(), 'Access to the requested resource is forbidden.')
        self.assertEqual(self.request.response.getStatus(), 403)

        getUtility(IAuthentication).status = 401
        self.assertEqual(
            view(), 'Access to the requested resource is forbidden.')
        self.assertEqual(self.request.response.getStatus(), 401)

        getUtility(IAuthentication).status = 302
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 302)

        getUtility(IAuthentication).status = 303
        self.assertEqual(view(), '')
        self.assertEqual(self.request.response.getStatus(), 303)
