"""
A traverser can set the __parent__ (and __name__) attributes itself,
in which case Grok's traverser won't interfere:

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
    The Three Stooges.
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
    The Three Stooges.
  </p>
  </body>
  </html>

"""
import grokcore.component as grok
import grokcore.content as content
import grokcore.view as view

import grokcore.traverser


class Herd(content.Model):

    def __init__(self, name):
        self.name = name


class HerdTraverser(grokcore.traverser.Traverser):
    grok.context(Herd)

    def traverse(self, name):
        mammoth = Mammoth(name)
        # We pretend the mammoth is the child object of some competely
        # differnt Herd object.
        mammoth.__parent__ = Herd('The Three Stooges')
        return mammoth


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
