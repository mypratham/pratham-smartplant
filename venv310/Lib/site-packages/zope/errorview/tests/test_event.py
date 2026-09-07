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

import zope.component.eventtesting
from zope.publisher.http import HTTPRequest

from zope.errorview.http import ExceptionViewBase
from zope.errorview.interfaces import IHandleExceptionEvent


class TestEvent(TestCase):
    def setUp(self):
        zope.component.eventtesting.setUp()
        self.request = HTTPRequest('', {})

    def test_event(self):
        ExceptionViewBase(Exception(), self.request)()
        event = zope.component.eventtesting.getEvents()[0]
        self.assertEqual(event.request, self.request)
        self.assertTrue(IHandleExceptionEvent.providedBy(event))
