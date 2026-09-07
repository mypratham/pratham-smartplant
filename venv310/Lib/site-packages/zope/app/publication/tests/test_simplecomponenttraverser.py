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
"""Sample Component Traverser Test
"""
import unittest

from zope.interface import Interface
from zope.interface import directlyProvides
from zope.publisher.interfaces import NotFound

from zope import component
from zope.app.publication.traversers import SimpleComponentTraverser


class ExampleInterface(Interface):
    pass


class Container:
    def __init__(self, **kw):
        for k in kw:
            setattr(self, k, kw[k])

    def get(self, name, default=None):
        return getattr(self, name, default)


class Request:

    def __init__(self, type):
        directlyProvides(self, type)

    def getEffectiveURL(self):
        return ''


class View:
    def __init__(self, comp, request):
        self._comp = comp


class Test(unittest.TestCase):

    def testAttr(self):
        # test container traver
        foo = Container()
        c = Container(foo=foo)
        req = Request(ExampleInterface)

        T = SimpleComponentTraverser(c, req)

        self.assertRaises(NotFound, T.publishTraverse, req, 'foo')

    def testView(self):
        # test getting a view
        foo = Container()
        c = Container(foo=foo)
        req = Request(ExampleInterface)

        T = SimpleComponentTraverser(c, req)
        component.provideAdapter(View, (None, ExampleInterface), Interface,
                                 name='foo')

        self.assertIs(T.publishTraverse(req, 'foo').__class__, View)

        self.assertRaises(NotFound, T.publishTraverse, req, 'morebar')


def test_suite():
    loader = unittest.TestLoader()
    return loader.loadTestsFromTestCase(Test)
