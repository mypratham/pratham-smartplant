import doctest
import importlib.resources
import unittest

from zope.testing import cleanup


def cleanUpZope(test):
    cleanup.cleanUp()


def suiteFromPackage(name):
    layer_dir = 'base'
    package = __package__
    resource_path = f'{layer_dir}/{name}'
    files = []
    files = [entry.name for entry in importlib.resources.files(
        package).joinpath(resource_path).iterdir() if entry.is_file()]
    suite = unittest.TestSuite()
    for filename in files:
        if not filename.endswith('.py'):
            continue
        if filename.endswith('_fixture.py'):
            continue
        if filename == '__init__.py':
            continue
        dottedname = 'grokcore.security.tests.{}.{}.{}'.format(
            layer_dir, name, filename[:-3])
        test = doctest.DocTestSuite(
            dottedname,
            tearDown=cleanUpZope,
            optionflags=(
                doctest.ELLIPSIS +
                doctest.NORMALIZE_WHITESPACE))
        suite.addTest(test)
    return suite


def test_suite():
    suite = unittest.TestSuite()
    for name in [
            'permissions',
            'role',
            'security']:
        suite.addTest(suiteFromPackage(name))
    return suite
