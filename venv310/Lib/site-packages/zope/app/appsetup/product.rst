Product-specific configuration
==============================

The ``product`` module of this package provides a very simple way to deal with
what has traditionally been called "product configuration", where "product"
refers to the classic Zope 2 notion of a product.

The configuration schema for the application server allows named
<product-config> sections to be added to the configuration file, and product
code can use the API provided by the module to retrieve configuration sections
for given names.

There are two public functions in the module that should be used in normal
operations, and additional functions and a class that can be used to help with
testing:

    >>> from __future__ import print_function
    >>> from zope.app.appsetup import product

Let's look at the helper class first, since we'll use it in describing the
public (application) interface.  We'll follow that with the functions for
normal operation, then the remaining test-support functions.


Faux configuration object
-------------------------

The ``FauxConfiguration`` class constructs objects that behave like the
ZConfig section objects to the extent needed for the product configuration
API.  These will be used here, and may also be used to create configurations
for testing components that consume such configuration.

The constructor requires two arguments: the name of the section, and a mapping
of keys to values that the section should provide.  Let's create a simple
example:

    >>> one = product.FauxConfiguration("one", {})
    >>> one.getSectionName()
    'one'
    >>> one.mapping
    {}

Providing a non-empty set of key/value pairs trivially behaves as expected:

    >>> two = product.FauxConfiguration("two", {"abc": "def"})
    >>> two.getSectionName()
    'two'
    >>> two.mapping
    {'abc': 'def'}


Application API
---------------

There are two functions in the application interface for this module.  One is
used by the configuration provider, and the other is used by the consumer.

The provider's API takes a sequence of configuration objects that conform to
the behaviors exhibited by the default ZConfig section objects.  Since the
``FauxConfiguration`` class provides these behaviors, we can easily see how
this can be used:

    >>> product.setProductConfigurations([one, two])

Now that we've established some configuration, we want to be able to use it.
We do this using the ``getProductConfiguration()`` function.  This function
takes a name and returns a matching configuration section if there is one, of
None if not:

    >>> product.getProductConfiguration("one")
    {}

    >>> product.getProductConfiguration("not-there") is None
    True

Note that for a section that exists, only the internal mapping is provided,
not the containing section object.  This is a historical wart; we'll just need
to live with it until new APIs are introduced.

Setting the configuration a second time will overwrite the prior
configuration; sections previously available will no longer be:

    >>> product.setProductConfigurations([two])
    >>> product.getProductConfiguration("one") is None
    True

The new sections are available, as expected:

    >>> product.getProductConfiguration("two")
    {'abc': 'def'}


Test support functions
----------------------

Additional functions are provided that make it easier to manage configuration
state in testing.

The first can be used to provide configuration for a single name.  The
function takes a name and either a configuration mapping or ``None`` as
arguments.  If ``None`` is provided as the second argument, any configuration
settings for the name are removed, if present.  If the second argument is not
``None``, it will be used as the return value for ``getProductConfiguration``
for the given name.

    >>> product.setProductConfiguration("first", None)
    >>> print(product.getProductConfiguration("first"))
    None

    >>> product.setProductConfiguration("first", {"key": "value1"})
    >>> product.getProductConfiguration("first")
    {'key': 'value1'}

    >>> product.setProductConfiguration("first", {"key": "value2"})
    >>> product.getProductConfiguration("first")
    {'key': 'value2'}

    >>> product.setProductConfiguration("first", {"alt": "another"})
    >>> product.getProductConfiguration("first")
    {'alt': 'another'}

    >>> product.setProductConfiguration("second", {"you": "there"})
    >>> product.getProductConfiguration("first")
    {'alt': 'another'}
    >>> product.getProductConfiguration("second")
    {'you': 'there'}

    >>> product.setProductConfiguration("first", None)
    >>> print(product.getProductConfiguration("first"))
    None

The other two functions work in concert, saving and restoring the entirety of
the configuration state.

Our current configuration includes data for the "second" key, and none for the
"first" key:

    >>> print(product.getProductConfiguration("first"))
    None
    >>> print(product.getProductConfiguration("second"))
    {'you': 'there'}

Let's save this state:

    >>> state = product.saveConfiguration()

Now let's replace the kitchen sink:

    >>> product.setProductConfigurations([
    ...     product.FauxConfiguration("x", {"a": "b"}),
    ...     product.FauxConfiguration("y", {"c": "d"}),
    ...     ])

    >>> print(product.getProductConfiguration("first"))
    None
    >>> print(product.getProductConfiguration("second"))
    None

    >>> product.getProductConfiguration("x")
    {'a': 'b'}
    >>> product.getProductConfiguration("y")
    {'c': 'd'}

The saved configuration state can be restored:

    >>> product.restoreConfiguration(state)

    >>> print(product.getProductConfiguration("x"))
    None
    >>> print(product.getProductConfiguration("y"))
    None

    >>> print(product.getProductConfiguration("first"))
    None
    >>> print(product.getProductConfiguration("second"))
    {'you': 'there'}

There's an additional function that can be used to load product configuration
from a file object; only product configuration components are accepted.  The
function returns a mapping of names to configuration objects suitable for
passing to ``setProductConfiguration``.  Using this with
``setProductConfigurations`` would require constructing ``FauxConfiguration``
objects.

Let's create some sample configuration text:

    >>> product_config = '''
    ... <product-config product1>
    ...   key1 product1-value1
    ...   key2 product1-value2
    ... </product-config>
    ...
    ... <product-config product2>
    ...   key1 product2-value1
    ...   key3 product2-value2
    ... </product-config>
    ... '''

We can now load the configuration using the ``loadConfiguration`` function:

    >>> import io
    >>> import pprint

    >>> sio = io.StringIO(product_config)
    >>> config = product.loadConfiguration(sio)

    >>> pprint.pprint(config, width=1)
    {'product1': {'key1': 'product1-value1',
                   'key2': 'product1-value2'},
     'product2': {'key1': 'product2-value1',
                   'key3': 'product2-value2'}}

Extensions that provide product configurations can be used as well:

    >>> product_config = '''
    ... %import zope.app.appsetup.testproduct
    ...
    ... <testproduct foobar>
    ... </testproduct>
    ...
    ... <testproduct barfoo>
    ...   key1 value1
    ...   key2 value2
    ... </testproduct>
    ... '''

    >>> sio = io.StringIO(product_config)
    >>> config = product.loadConfiguration(sio)

    >>> pprint.pprint(config, width=1)
    {'barfoo': {'key1': 'value1',
                 'key2': 'value2',
                 'product-name': 'barfoo'},
     'foobar': {'product-name': 'foobar'}}
