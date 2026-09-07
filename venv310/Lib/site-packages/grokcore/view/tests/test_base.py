import doctest
import os
import unittest
from importlib.resources import files

import zope.component.eventtesting
from zope.testing import cleanup

import grokcore.view
from grokcore.view.templatereg import file_template_registry


optionflags = (
    doctest.NORMALIZE_WHITESPACE +
    doctest.ELLIPSIS
)


def setUp(test):
    zope.component.eventtesting.setUp(test)
    file_template_registry.ignore_templates('.svn')


def cleanUp(test):
    cleanup.cleanUp()


def suiteFromPackage(name):
    layer_dir = 'base'
    package_files = files('grokcore.view.tests')
    resource_dir = package_files / layer_dir / name
    file_list = [f.name for f in resource_dir.iterdir()]
    suite = unittest.TestSuite()
    for filename in file_list:
        if filename.endswith('_fixture.py'):
            continue
        if filename == '__init__.py':
            continue
        test = None
        if filename.endswith('.py'):
            dottedname = 'grokcore.view.tests.{}.{}.{}'.format(
                layer_dir, name, filename[:-3])
            test = doctest.DocTestSuite(
                dottedname,
                setUp=setUp,
                tearDown=cleanUp,
                optionflags=optionflags)
        elif filename.endswith('.txt'):
            test = doctest.DocFileSuite(
                os.path.join(layer_dir, name, filename),
                optionflags=optionflags,
                setUp=setUp,
                tearDown=cleanUp,
                globs={'grok': grokcore.view})
        if test is not None:
            suite.addTest(test)
    return suite


def test_suite():
    suite = unittest.TestSuite()
    for name in [
            'contentprovider',
            'directoryresource',
            'skin',
            'template',
            'view']:
        suite.addTest(suiteFromPackage(name))
    suite.addTest(doctest.DocFileSuite(
        '../templatereg.txt',
        optionflags=optionflags,
        setUp=setUp,
        tearDown=cleanUp,
    ))
    return suite
