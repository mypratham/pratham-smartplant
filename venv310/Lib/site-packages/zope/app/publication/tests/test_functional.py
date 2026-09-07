##############################################################################
#
# Copyright (c) 2004 Zope Foundation and Contributors.
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
"""Test not found errors
"""

import doctest
import re
import unittest

from zope.testing import renormalizing

from zope.app.publication.testing import PublicationLayer


checker = renormalizing.RENormalizing([
    (re.compile(r"HTTP/1\.([01]) (\d\d\d) .*"), r"HTTP/1.\1 \2 <MESSAGE>"),
])

excchecker = renormalizing.RENormalizing([
    (re.compile(r"zope.publisher.interfaces.http.MethodNotAllowed"),
     "MethodNotAllowed")
])

optionflags = doctest.ELLIPSIS + doctest.NORMALIZE_WHITESPACE


def setUpTestLayer(test):
    test.globs['wsgi_app'] = PublicationLayer.make_wsgi_app()


def test_suite():
    methodnotallowed = doctest.DocFileSuite(
        '../methodnotallowed.rst', setUp=setUpTestLayer,
        optionflags=optionflags, checker=excchecker)
    methodnotallowed.layer = PublicationLayer
    notfound = doctest.DocFileSuite(
        '../notfound.rst', setUp=setUpTestLayer,
        optionflags=optionflags)
    notfound.layer = PublicationLayer
    httpfactory = doctest.DocFileSuite(
        '../httpfactory.rst', checker=checker, setUp=setUpTestLayer,
        optionflags=optionflags)
    httpfactory.layer = PublicationLayer
    site = doctest.DocFileSuite(
        '../site.rst',
        optionflags=optionflags)
    site.layer = PublicationLayer
    return unittest.TestSuite((
        methodnotallowed,
        notfound,
        httpfactory,
        site,))
