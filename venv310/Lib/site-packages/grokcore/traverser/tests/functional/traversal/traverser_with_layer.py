"""
Apart from using the ``traverse`` method on a model, you can
also create a separate traverser component:

  >>> getRootFolder()["herd"] = Herd('The Big Mammoth Herd')

  >>> from zope.testbrowser.wsgi import Browser
  >>> browser = Browser()
  >>> browser.handleErrors = False
  >>> browser.open("http://localhost/herd/manfred")
  >>> print(browser.contents)
  <html>
  <body>
  <h1>Hello, Manfred!</h1>
  <p>
    Manfred
    is part of
    The Big Mammoth Herd.
  </p>
  </body>
  </html>

  >>> browser.open("http://localhost/herd/ellie")
  >>> print(browser.contents)
  <html>
  <body>
  <h1>Hello, Ellie!</h1>
  <p>
    Ellie
    is part of
    The Big Mammoth Herd.
  </p>
  </body>
  </html>

Now let's call the same URI on a different Layer.

  >>> browser.open("http://localhost/++skin++elephant/herd/ellie")
  >>> print(browser.contents)
  <html>
  <body>
  <h1>Hello, Ellie Elephant!</h1>
  <p>
    Ellie Elephant
    is part of
    The Big Mammoth Herd.
  </p>
  </body>
  </html>
"""
import grokcore.component as grok
import grokcore.content as content
import grokcore.view as view

import grokcore.traverser


class ElephantLayer(view.IDefaultBrowserLayer):
    pass


class ElephantSkin(ElephantLayer):
    view.skin('elephant')


class Herd(content.Model):

    def __init__(self, name):
        self.name = name


class HerdTraverser(grokcore.traverser.Traverser):
    grok.context(Herd)

    def traverse(self, name):
        return Mammoth(name)


class ElephantTraverser(grokcore.traverser.Traverser):
    grok.context(Herd)
    view.layer(ElephantLayer)

    def traverse(self, name):
        return Mammoth(name + ' Elephant')


class Mammoth(content.Model):

    def __init__(self, name):
        self.name = name


grok.context(Mammoth)


class Index(view.View):
    pass


index = view.PageTemplate("""\
<html>
<body>
<h1>Hello, <span tal:replace="context/name/title" />!</h1>
<p>
  <span tal:replace="context/name/title" />
  is part of
  <span tal:replace="context/__parent__/name" />.
</p>
</body>
</html>
""")
