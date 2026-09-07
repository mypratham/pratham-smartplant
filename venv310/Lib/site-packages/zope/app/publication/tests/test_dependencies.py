import unittest

from zope.component import getMultiAdapter
from zope.component.testlayer import ZCMLFileLayer
from zope.publisher.browser import TestRequest
from zope.publisher.interfaces.browser import IBrowserPublisher

import zope.app.publication.tests
from zope.app.publication.traversers import SimpleComponentTraverser


class ZCMLDependencies(unittest.TestCase):
    layer = ZCMLFileLayer(zope.app.publication.tests,
                          zcml_file='ftest_zcml_dependencies.zcml',
                          name='PublicationDependenciesLayer')

    def test_zcml_can_load_with_only_zope_component_meta(self):
        # this is just an example.  It is supposed to show that the
        # configure.zcml file has loaded successfully.

        request = TestRequest()

        sample = object()
        res = getMultiAdapter(
            (sample, request), IBrowserPublisher)
        self.assertIsInstance(res, SimpleComponentTraverser)
        self.assertIs(res.context, sample)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(
        ZCMLDependencies))
    return suite
