import doctest
import os.path
import unittest
from importlib.resources import files

import zope.app.wsgi.testlayer
import zope.testbrowser.wsgi

import grokcore.view
import grokcore.view.testing


class Layer(
        zope.testbrowser.wsgi.TestBrowserLayer,
        zope.app.wsgi.testlayer.BrowserLayer):
    pass


layer = Layer(grokcore.view, allowTearDown=True)


def suiteFromPackage(name):
    layer_dir = 'functional'
    package_files = files('grokcore.view.tests')
    resource_dir = package_files / layer_dir / name
    file_list = [f.name for f in resource_dir.iterdir()]
    suite = unittest.TestSuite()
    getRootFolder = layer.getRootFolder
    globs = dict(
        getRootFolder=getRootFolder,
        http=zope.app.wsgi.testlayer.http,
        wsgi_app=layer.make_wsgi_app
    )
    optionflags = (
        doctest.ELLIPSIS +
        doctest.NORMALIZE_WHITESPACE +
        doctest.REPORT_NDIFF +
        doctest.IGNORE_EXCEPTION_DETAIL
    )

    for filename in file_list:
        if filename == '__init__.py':
            continue

        test = None
        if filename.endswith('.py'):
            dottedname = 'grokcore.view.tests.{}.{}.{}'.format(
                layer_dir, name, filename[:-3])
            test = doctest.DocTestSuite(
                dottedname,
                extraglobs=globs,
                optionflags=optionflags)
            test.layer = layer
        elif filename.endswith('.txt'):
            test = doctest.DocFileSuite(
                os.path.join(layer_dir, name, filename),
                optionflags=optionflags,
                globs=globs)
            test.layer = layer
        if test is not None:
            suite.addTest(test)
    return suite


def test_suite():
    suite = unittest.TestSuite()
    for name in [
            'contentprovider',
            'directoryresource',
            'static',
            'url',
            'view']:
        suite.addTest(suiteFromPackage(name))
    return suite
