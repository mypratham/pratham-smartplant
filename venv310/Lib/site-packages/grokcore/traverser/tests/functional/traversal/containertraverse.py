"""
Containers can determine how they want to be traversed by
implementing a 'traverse' method, but the behavior falls back to
basic container traversal if the 'traverse' method returns None:

  >>> getRootFolder()["herd"] = herd = Herd()
  >>> herd['manfred'] = Mammoth('Manfred')
  >>> herd['ellie'] = Mammoth('Ellie')

Let's first try to look up the special traversed item:

  >>> from zope.testbrowser.wsgi import Browser
  >>> browser = Browser()
  >>> browser.handleErrors = False
  >>> browser.open("http://localhost/herd/special")
  >>> print(browser.contents)
  special view
  >>> browser.open("http://localhost/herd/special/index")
  >>> print(browser.contents)
  special view

Even if we have a container item called 'special', we should still
get our special object:

  >>> herd['special'] = Mammoth('Special invisible mammoth')
  >>> browser.open("http://localhost/herd/special")
  >>> print(browser.contents)
  special view
  >>> browser.open("http://localhost/herd/special/index")
  >>> print(browser.contents)
  special view

The fall-back behavior should work for items that aren't traversed:

  >>> browser.open("http://localhost/herd/manfred")
  >>> print(browser.contents)
  <html>
  <body>
  <h1>Hello, Manfred!</h1>
  </body>
  </html>

  >>> browser.open("http://localhost/herd/ellie")
  >>> print(browser.contents)
  <html>
  <body>
  <h1>Hello, Ellie!</h1>
  </body>
  </html>

Also try (an empty and therefore False in a Boolean sense) container
as a subitem of a container:

  >>> herd['subherd'] = Herd()
  >>> browser.open("http://localhost/herd/subherd")
  >>> print(browser.contents)
  A herd

"""
import grokcore.component as grok
import grokcore.content as content
import grokcore.view as view


class Herd(content.Container):

    def traverse(self, name):
        if name == 'special':
            return Special()
        return None


class HerdIndex(view.View):
    grok.context(Herd)
    grok.name('index')

    def render(self):
        return 'A herd'


class Mammoth(content.Model):

    def __init__(self, name):
        self.name = name


class Special(content.Model):
    pass


class SpecialIndex(view.View):
    grok.context(Special)
    grok.name('index')

    def render(self):
        return "special view"


grok.context(Mammoth)


class Index(view.View):
    pass


index = view.PageTemplate("""\
<html>
<body>
<h1>Hello, <span tal:replace="context/name/title" />!</h1>
</body>
</html>
""")
