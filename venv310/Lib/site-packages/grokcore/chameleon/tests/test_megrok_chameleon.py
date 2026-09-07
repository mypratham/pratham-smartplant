"""Test setup for grokcore.chameleon.
"""
import doctest
import re
import unittest

import zope.component
import zope.interface
from zope.publisher.interfaces.browser import IBrowserRequest
from zope.testing import renormalizing
from zope.traversing.browser.interfaces import IAbsoluteURL
from zope.traversing.interfaces import ITraversable

import grokcore.chameleon
from grokcore.chameleon.tests import FunctionalLayer


FLAGS = (doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE)


@zope.interface.implementer(ITraversable, IAbsoluteURL)
class DummyResource:
    """ Dummy resource implementation. """

    def __init__(self, request, name=''):
        self.request = request
        self.name = name

    def traverse(self, name, furtherPath):
        name = f'{self.name}/{name}'
        return DummyResource(self.request, name=name)

    def __str__(self):
        return 'dummy:%s' % self.name


def setUpStatic(test):
    # Register a dummy resource for static folder.
    zope.component.provideAdapter(
        factory=DummyResource,
        adapts=(IBrowserRequest,),
        provides=zope.interface.Interface,
        name='grokcore.chameleon.tests.cpt_fixture'
    )


checker = renormalizing.RENormalizing([
    (re.compile(
        r"IOError: \[Errno 2\] No such file or directory: "),
        r'FileNotFoundError: [Errno 2] No such file or directory: ')
])


def test_suite():
    """Get a testsuite of all doctests.
    """
    suite = unittest.TestSuite()
    readme = doctest.DocFileSuite(
        'README.rst',
        checker=checker,
        setUp=setUpStatic,
        package=grokcore.chameleon,
        globs=dict(
            getRootFolder=FunctionalLayer.getRootFolder,
        ),
        optionflags=FLAGS,
    )
    readme.layer = FunctionalLayer
    suite.addTest(readme)
    suite.addTest(
        doctest.DocTestSuite(
            'grokcore.chameleon.tests.templatefile',
            checker=checker,
            setUp=setUpStatic,
            optionflags=FLAGS,
        )
    )
    return suite
