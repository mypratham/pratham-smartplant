import doctest
import unittest
from importlib import import_module
from importlib.resources import files

from zope.app.appsetup.testlayer import ZODBLayer

import grokcore.site


def resource_listdir(package_name, resource_path):
    """List resources in a package subdirectory."""
    # Get the package from the module name
    module = import_module(package_name)
    package = module.__package__ or package_name

    resource = files(package)
    for part in resource_path.split('/'):
        resource = resource / part
    return [item.name for item in resource.iterdir()]


FunctionalLayer = ZODBLayer(grokcore.site)


def suiteFromPackage(name):
    layer_dir = 'functional'
    files = resource_listdir(__name__, f'{layer_dir}/{name}')
    suite = unittest.TestSuite()
    for filename in files:
        if not filename.endswith('.py'):
            continue
        if filename == '__init__.py':
            continue

        dottedname = 'grokcore.site.tests.{}.{}.{}'.format(
            layer_dir, name, filename[:-3])
        test = doctest.DocTestSuite(
            dottedname,
            extraglobs=dict(getRootFolder=FunctionalLayer.getRootFolder),
            optionflags=(
                doctest.ELLIPSIS +
                doctest.NORMALIZE_WHITESPACE +
                doctest.REPORT_NDIFF))
        test.layer = FunctionalLayer

        suite.addTest(test)
    return suite


def test_suite():
    suite = unittest.TestSuite()
    for name in ['utility', 'site', 'application']:
        suite.addTest(suiteFromPackage(name))
    return suite
