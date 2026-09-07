"""Test harness"""

import doctest
import unittest

from zope.component.testlayer import ZCMLFileLayer
from zope.publisher.browser import TestRequest
from zope.security.management import endInteraction
from zope.security.management import newInteraction

import grokcore.message


class GrokcoreMessageLayer(ZCMLFileLayer):

    def setUp(self):
        ZCMLFileLayer.setUp(self)
        newInteraction(TestRequest())

    def tearDown(self):
        endInteraction()
        ZCMLFileLayer.tearDown(self)


def test_suite():
    suite = unittest.TestSuite()
    test = doctest.DocFileSuite(
        'README.rst', optionflags=(doctest.ELLIPSIS |
                                   doctest.IGNORE_EXCEPTION_DETAIL))
    test.layer = GrokcoreMessageLayer(grokcore.message)
    suite.addTest(test)
    return suite
