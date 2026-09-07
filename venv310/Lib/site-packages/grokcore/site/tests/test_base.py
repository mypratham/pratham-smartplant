import doctest
import unittest
from importlib import import_module
from importlib.resources import files

import zope.component.eventtesting
from zope.testing import cleanup


def resource_listdir(package_name, resource_path):
    """List resources in a package subdirectory."""
    # Get the package from the module name
    module = import_module(package_name)
    package = module.__package__ or package_name

    resource = files(package)
    for part in resource_path.split('/'):
        resource = resource / part
    return [item.name for item in resource.iterdir()]


def setUpZope(test):
    zope.component.eventtesting.setUp(test)


def cleanUpZope(test):
    cleanup.cleanUp()


def suiteFromPackage(name):
    layer_dir = 'base'
    files = resource_listdir(__name__, f'{layer_dir}/{name}')
    suite = unittest.TestSuite()
    for filename in files:
        if not filename.endswith('.py'):
            continue
        if filename.endswith('_fixture.py'):
            continue
        if filename == '__init__.py':
            continue

        dottedname = 'grokcore.site.tests.{}.{}.{}'.format(
            layer_dir, name, filename[:-3])
        test = doctest.DocTestSuite(
            dottedname,
            setUp=setUpZope,
            tearDown=cleanUpZope,
            optionflags=doctest.ELLIPSIS + doctest.NORMALIZE_WHITESPACE)

        suite.addTest(test)
    return suite


def test_suite():
    suite = unittest.TestSuite()
    for name in ['utility', 'application']:
        suite.addTest(suiteFromPackage(name))
    return suite
