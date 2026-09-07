====================
Detailed Description
====================

Grok-support for using chameleon driven templates.

With `grokcore.chameleon` you can use templates parsed and rendered by
`Chameleon`_ using the Zope Page Template templating language.

Chameleon Zope page templates
=============================

Chameleon provides support for Zope page templates which can be used
from grok writing templates with the ``.cpt`` (=Chameleon Page
Template) filename extension.

Chameleon page templates differ from standard Zope page templates in a
few aspects, most notably:

* Expressions are parsed in ``Python-mode`` by default. This means,
  instead of ``tal:content="view/value"`` you must use
  ``tal:content="view.value"``. Every occurence of TAL-expressions
  starting with ``python:`` now can be shortened by skipping this
  marker.

* Also Genshi-like variable substitutions are supported. For example
  you can write ``${myvar}`` instead of ``tal:content="myvar"``.

Beside this, most rules for regular Zope page templates apply also to
chameleon page templates.

See the `Chameleon`_ page for more information.

.. _Chameleon: http://chameleon.repoze.org/docs/latest/zpt.html

Prerequisites
=============

Before we can see the templates in action, we care for correct
registration and set some used variables:

    >>> import os
    >>> testdir = os.path.join(os.path.dirname(__file__), 'tests')
    >>> cpt_fixture = os.path.join(testdir, 'cpt_fixture')
    >>> template_dir = os.path.join(cpt_fixture, 'app_templates')

We register everything. Before we can grok our fixture, we have to
grok the `grokcore.chameleon` package. This way the new template types
are registered with the framework:

    >>> import grokcore.view
    >>> grokcore.view.testing.grok('grokcore.chameleon')
    >>> grokcore.view.testing.grok('grokcore.chameleon.tests.cpt_fixture')

We create a mammoth, which should provide us a bunch of chameleon page
template driven views and put it in the database to setup location
info::

    >>> from grokcore.chameleon.tests.cpt_fixture.app import Mammoth
    >>> manfred = Mammoth()
    >>> getRootFolder()['manfred'] = manfred

Furthermore we prepare for getting the different views on manfred:

    >>> from zope.publisher.browser import TestRequest
    >>> from zope.component import getMultiAdapter
    >>> request = TestRequest()

Simple templates
================

We prepared a plain cavepainting view. The template looks like this:

    >>> cavepainting_cpt = os.path.join(template_dir, 'cavepainting.cpt')
    >>> with open(cavepainting_cpt, 'r') as f:
    ...     print(f.read())
    <html>
      <body>
        A cave painting.
      </body>
    </html>

The rendered view looks like this:

    >>> view = getMultiAdapter((manfred, request),
    ...                         name='cavepainting')
    >>> print(view())
    <html>
      <body>
        A cave painting.
      </body>
    </html>

Substituting variables
======================

A template can access variables like ``view``, ``context``, ``static``
and its methods and attributes. The ``food`` view does exactly
this. The template looks like this:

    >>> food_cpt = os.path.join(template_dir, 'food.cpt')
    >>> with open(food_cpt, 'r') as f:
    ...     print(f.read())
    <html>
    <body>
    <span tal:define="foo 'a FOO'">
    ${view.me_do()}
    <span tal:replace="structure view.me_do()" />
    CSS-URL: ${path:static/test.css}
    My context is: ${view.url(context)}
    ${foo}
    <span tal:replace="foo" />
    </span>
    </body>
    </html>

The rendered view looks like this:

    >>> view = getMultiAdapter((manfred, request), name='food')
    >>> print(view())
    <html>
    <body>
    <span>
    &lt;ME GROK EAT MAMMOTH!&gt;
    <ME GROK EAT MAMMOTH!>
    CSS-URL: dummy:/test.css
    My context is: http://127.0.0.1/manfred
    a FOO
    a FOO
    </span>
    </body>
    </html>

As we can see, there is a difference between Genshi-like substitution
and TAL-like substitution: while both expressions::

  ${view.me_do()}

and::

  <span tal:replace="view.me_do()" />

actually render the same string ``<ME GROK EAT MAMMOTH!>``, the former
does this straight and plain, while the latter performs additionally
HTML-encoding of the string. Therefore the output of both expressions
differ. It's::

  <ME GROK EAT MAMMOTH!>

for the former expression and::

  &lt;ME GROK EAT MAMMOTH!&gt;

for the latter.


Supported variables
===================

Each template provides at least the following vars:

* ``template``
    the template instance

* ``view``
    the associated view

* ``context``
    the context of the view

* ``request``
    the current request

as we can see, when we look at the ``vars.cpt`` from our fixture:

    >>> cpt_file = os.path.join(template_dir, 'vars.cpt')
    >>> with open(cpt_file, 'r') as f:
    ...     print(f.read())
    <html>
    <body>
    This template knows about the following vars:
    <BLANKLINE>
      template (the template instance):
       ${template}
    <BLANKLINE>
      view (the associated view):
       ${view}
    <BLANKLINE>
      context (the context of the view):
       ${context}
    <BLANKLINE>
      request (the current request):
       ${request}
    </body>
    </html>

and render it:

    >>> view = getMultiAdapter((manfred, request), name='vars')
    >>> print(view())
    <html>
    <body>
    This template knows about the following vars:
    <BLANKLINE>
      template (the template instance):
       &lt;PageTemplateFile ...vars.cpt&gt;
    <BLANKLINE>
      view (the associated view):
       &lt;grokcore.chameleon.tests.cpt_fixture.app.Vars object at 0x...&gt;
    <BLANKLINE>
      context (the context of the view):
       &lt;grokcore.chameleon.tests.cpt_fixture.app.Mammoth object at 0x...&gt;
    <BLANKLINE>
      request (the current request):
       CONTENT_LENGTH:	0
    GATEWAY_INTERFACE:	TestFooInterface/1.0
    HTTP_HOST:	127.0.0.1
    SERVER_URL:	http://127.0.0.1
    </body>
    </html>

Custom template namespace names are supported:

    >>> view = getMultiAdapter((manfred, request), name='namespace')
    >>> print(view())
    <html>
    <body>
    This template knows about the following custom namespace name:
    <BLANKLINE>
      myname:
       Henk
    <BLANKLINE>
    </body>
    </html>

Inline Templates
================

We can also define inline templates. In our ``app.py`` we defined an
inline template like this::

  from grokcore.chameleon import components

  ...

  class Inline(grokcore.view.View):
    sometext = 'Some Text'

  inline = components.ChameleonPageTemplate(
      "<html><body>ME GROK HAS INLINES! ${view.sometext}</body></html>")

If we render this view we get:

    >>> view = getMultiAdapter((manfred, request), name='inline')
    >>> print(view())
    <html><body>ME GROK HAS INLINES! Some Text</body></html>

TAL expressions
===============

Starting with ``grokcore.chameleon`` 0.5 we deploy the all-in-one
`Chameleon`_ package.

What TAL/TALES expressions in templates are supported depends mainly
from the installed version of `Chameleon`, while we support some
additional, Zope-related TALES expressions.

A list of all supported expressions and statements can be found at the
`chameleon.zpt documentation
<http://chameleon.repoze.org/docs/latest/zpt.html>`_. The additional
TALES expressions provided by ``grokcore.chameleon`` are:

* ``exists``
     Tell whether a name exists in the templates' namespace.

* ``not``
     Evaluate the expression to a boolean value and invert it.

* ``path``
     Handle the expression as a path and not as a Python expression.

* ``provider``
     Support for viewlet providers.

.. note:: Starting with ``grokcore.chameleon`` 0.5 support for the
          Python expression ``exists()`` has been dropped. The TALES
          expression ``exists: path/to/something`` is still available.

In our ``app.py`` we defined a special view for showing some special
expressions. This also includes a viewlet::

   import grok
   from grokcore.chameleon import components

   class Mammoth(grok.Application, grok.Container):
       pass

   ...

   class Expressions(grok.View):
       pass

   class MainArea(grok.ViewletManager):
       grok.name('main')

   class MainContent(grok.Viewlet):
       grok.view(Expressions)
       grok.viewletmanager(MainArea)
       def render(self):
           return 'Hello from viewlet'

Now we can make use of the TALES expressions ``not:``, ``path:``,
``exists:`` and ``provider:`` in the ``expressions.cpt`` template of
our fixture:

    >>> cpt_file = os.path.join(template_dir, 'expressions.cpt')
    >>> with open(cpt_file, 'r') as f:
    ...     print(f.read())
    <html>
    <body>
      <div tal:define="food 'Yummy Dinoburger'"
           tal:omit-tag="">
        <!-- We support `exists` -->
        <div tal:condition="exists: food">
          ${food}
        </div>
    <BLANKLINE>
        <!-- We support `not` -->
        <div tal:content="not: food" />
        <div tal:content="not('food')" />
        <div tal:content="not: 1 in [2,3]" />
        <div tal:content="not: not: food" />
    <BLANKLINE>
        <!-- We support `path` -->
        <div tal:content="path: food/upper" />
    <BLANKLINE>
        <!-- We support `provider` -->
        <tal:main content="structure provider:main" />
    <BLANKLINE>
      </div>
    </body>
    </html>

and render it:

    >>> view = getMultiAdapter((manfred, request), name='expressions')
    >>> print(view())
    <html>
    <body>
    <BLANKLINE>
        <!-- We support `exists` -->
        <div>
          Yummy Dinoburger
        </div>
    <BLANKLINE>
        <!-- We support `not` -->
        <div>False</div>
        <div>False</div>
        <div>True</div>
        <div>True</div>
    <BLANKLINE>
        <!-- We support `path` -->
        <div>YUMMY DINOBURGER</div>
    <BLANKLINE>
        <!-- We support `provider` -->
        Hello from viewlet
    <BLANKLINE>
    <BLANKLINE>
    </body>
    </html>

Translation
===========

    >>> # Monkeypatch zope.i18n.negotiate
    >>> import zope.i18n
    >>> import zope.i18n.config
    >>> print(getMultiAdapter((manfred, request), name='menu')())
    <html>
    <body>
      <h1>Menu</h1>
      <ol>
        <li>Deepfried breaded veal cutlets</li>
        <li>Variants: ['raw', 'bloody']</li>
      </ol>
    </body>
    </html>

Unhashable types might be used as message ids: They do not break, but do not get
translated either.

    >>> # What's for food today in Germany?
    >>> # We need to monkey patch the language settings for this test.
    >>> old_1, old_2 = zope.i18n.negotiate, zope.i18n.config.ALLOWED_LANGUAGES
    >>> zope.i18n.negotiate = lambda context: 'de'
    >>> zope.i18n.config.ALLOWED_LANGUAGES = ['de']
    >>> print(getMultiAdapter((manfred, request), name='menu')())
    <html>
    <body>
      <h1>Menu</h1>
      <ol>
        <li>Schnitzel</li>
        <li>Variants: ['raw', 'bloody']</li>
      </ol>
    </body>
    </html>

    >>> # Restore the monkey patch.
    >>> zope.i18n.negotiate, zope.i18n.config.ALLOWED_LANGUAGES = old_1, old_2

Macros
======

With ``grokcore.chameleon`` we can also use macros, although it is a bit
different from regular Zope page templates.

We can define macros like this:

    >>> cpt_file = os.path.join(template_dir, 'macromaster.cpt')
    >>> with open(cpt_file, 'r') as f:
    ...     print(f.read())
    <p xmlns:metal="http://xml.zope.org/namespaces/metal"
       metal:define-macro="hello">
      Hello from <b metal:define-slot="name">macro master</b>
    </p>

The defined macro ``hello`` can be rendered in another Chameleon
template with the METAL attribute ``use-macro``.

To refer to a local macro, i.e. a macros defined in the same template,
you can use something like::

  <div metal:use-macro="template.macros['<macro-name>']">
    Replaced by macro
  </div>

where ``<macro-name>`` must be an existing macro name.

To refer to macros in external templates, you must use the ``path:`` expression
like this::

  <div metal:use-macro="path:
    context/@@<viewname>/template/macros/<macro-name>">
     Replaced by external macro
  </div>

where ``<viewname>`` refers to an existing view on ``context`` and ``macro-
name`` again refers to an existing macro in the specified template.

Note, that this is different from how you refer to macros in standard Zope page
templates. The short notation ``view/macros/<macro-name>`` works only with
regular Zope page templates.

The following template makes use of both methods:

    >>> cpt_file = os.path.join(template_dir, 'macrouser.cpt')
    >>> with open(cpt_file, 'r') as f:
    ...     print(f.read())
    <html xmlns:metal="http://xml.zope.org/namespaces/metal">
    <body>
      <p metal:define-macro="hello">
        Hi there from macro user!
      </p>
      <div metal:use-macro="template.macros['hello']">
        Fill this
      </div>
    <BLANKLINE>
      <div metal:use-macro="path: context/@@macromaster/template/macros/hello">
        <b metal:fill-slot="name">user slot</b>
        Fill this too
      </div>
    </body>
    </html>

When rendered also the slot defined in the master template is filled by macro
user content:

    >>> cpt_file = os.path.join(template_dir, 'macrouser.cpt')
    >>> view = getMultiAdapter((manfred, request), name='macrouser')
    >>> print(view())
    <html>
    <body>
      <p>
        Hi there from macro user!
      </p>
      <p>
        Hi there from macro user!
      </p>
    <BLANKLINE>
    <BLANKLINE>
      <p>
      Hello from <b>user slot</b>
    <BLANKLINE>
    </p>
    </body>
    </html>


Clean up:

    >>> del getRootFolder()['manfred']

Differences from regular Zope page templates
============================================

* Macros are referenced differently. See appropriate section above.

* Expressions are parsed in ``Python-mode`` by default. This means, instead
  of ``tal:content="view/value"`` you must use ``tal:content="view.value"``.
  Every occurence of TAL-expressions starting with ``python:`` now can be
  shortened by skipping this marker.
