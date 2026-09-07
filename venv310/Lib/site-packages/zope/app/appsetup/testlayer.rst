Layers
======

zope.app.appsetup.testlayer define a test layer which creates a test
database.

ZODBLayer
---------

We can instantiate a ZODBLayer::

  >>> from zope.app.appsetup.testlayer import ZODBLayer
  >>> from zope.app.appsetup import testpackage

  >>> layer = ZODBLayer(testpackage)
  >>> layer
  <zope.app.appsetup.testlayer.ZODBLayer object at ...>

Now we run some tests with this layer that checks that we have a
working database::

  >>> import unittest
  >>> import transaction
  >>> from zope import component
  >>> from zope.app.appsetup.testpackage import testobject
  >>> from ZODB.interfaces import IDatabase

  >>> class TestCase(unittest.TestCase):
  ...    layer = layer
  ...
  ...    def testAddObjectInDB(self):
  ...        root = self.layer.getRootFolder()
  ...        root['object'] = testobject.TestObject()
  ...        transaction.commit()
  ...        self.assertIn('object', root)
  ...    def testNoMoreObjectInDB(self):
  ...        root = self.layer.getRootFolder()
  ...        self.assertNotIn('object', root)
  ...    def testApplicationInDB(self):
  ...        root = self.layer.getRootFolder()
  ...        self.assertEqual(
  ...            repr(root.__class__), "<class 'zope.site.folder.Folder'>")
  ...    def testDBRegistered(self):
  ...        root = self.layer.getRootFolder()
  ...        db = component.getUtility(IDatabase, name='main')
  ...        self.assertEqual(db, root._p_jar.db())

We define a suite with our test:

  >>> suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestCase)

And run that suite:

  >>> from zope.testrunner.runner import Runner
  >>> runner = Runner(args=[], found_suites=[suite])
  >>> succeeded = runner.run()
  Running zope.app.appsetup.testpackage.ZODBLayer tests:
    Set up zope.app.appsetup.testpackage.ZODBLayer in ... seconds.
    Ran 4 tests with 0 failures, 0 errors and 0 skipped in ... seconds.
  Tearing down left over layers:
    Tear down zope.app.appsetup.testpackage.ZODBLayer in ... seconds.

Database stacking with ZODBlayer
--------------------------------

When deriving from ZODBLayer we can start populating a test database at layer
setup time. Each test will be run with a DemoStorage wrapped around that
baseline and unwrapped afterwards. This way you can save a significant amount
of time if tests require shared setup.

We start with a derived layer, based on ZODBLayer that has some setup code:

  >>> class CustomZODBLayer(ZODBLayer):
  ...     def setUp(self):
  ...         super(CustomZODBLayer, self).setUp()
  ...         root = self.getRootFolder()
  ...         root['foo'] = 1
  ...         transaction.commit()

  >>> layer = CustomZODBLayer(testpackage)
  >>> layer.__class__
  <class 'CustomZODBLayer'>

Now, when running tests in this layer, each test sees the prepopulated
database but is still isolated from other tests' changes:

  >>> class CustomZODBLayerTests(unittest.TestCase):
  ...     layer = layer
  ...     def test_test1(self):
  ...         root = self.layer.getRootFolder()
  ...         self.assertEqual(1, len(root))
  ...         root['bar'] = 1
  ...         transaction.commit()
  ...     def test_test2(self):
  ...         root = self.layer.getRootFolder()
  ...         self.assertEqual(1, len(root))
  ...         root['baz'] = 1
  ...         transaction.commit()

Run the tests to prove that above statements are correct::

  >>> suite = unittest.defaultTestLoader.loadTestsFromTestCase(
  ...     CustomZODBLayerTests)

And run that suite:

  >>> from zope.testrunner.runner import Runner
  >>> runner = Runner(args=[], found_suites=[suite])
  >>> succeeded = runner.run()
  Running zope.app.appsetup.testpackage.CustomZODBLayer tests:
    Set up zope.app.appsetup.testpackage.CustomZODBLayer in ... seconds.
    Ran 2 tests with 0 failures, 0 errors and 0 skipped in ... seconds.
  Tearing down left over layers:
    Tear down zope.app.appsetup.testpackage.CustomZODBLayer in ... seconds.
