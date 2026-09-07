"""
We can use grok.AddForm to render an add form for objects:

  >>> getRootFolder()["zoo"] = Zoo()

  >>> from zope.testbrowser.wsgi import Browser
  >>> browser = Browser()
  >>> browser.handleErrors = False

  >>> browser.open("http://localhost/zoo/@@addmammoth")
  >>> browser.getControl(name="form.name").value = "Manfred the Mammoth"
  >>> browser.getControl(name="form.size").value = "Really big"
  >>> browser.getControl("Add entry").click()
  >>> print(browser.contents)
  Hi, my name is Manfred the Mammoth, and I\'m "Really big"

Instead of calling an object constructor with the form data, we can
also use the ``applyData`` method to store the data on the object.

  >>> browser.open("http://localhost/zoo/@@addmammothapplydata")
  >>> browser.getControl(name="form.name").value = "Ellie the Mammoth"
  >>> browser.getControl(name="form.size").value = "Really small"
  >>> browser.getControl("Add entry").click()
  >>> print(browser.contents)
  Hi, my name is Ellie the Mammoth, and I\'m "Really small"

"""
from zope import schema
from zope.container.btree import BTreeContainer
from zope.container.contained import Contained
from zope.container.interfaces import IContainer
from zope.interface import Interface
from zope.interface import implementer

import grokcore.formlib as grok


class Zoo(grok.testing.Model, BTreeContainer):
    grok.testing.protect_get(grok.Public, *IContainer)


class IMammoth(Interface):
    name = schema.TextLine(title="Name")
    size = schema.TextLine(title="Size", default="Quite normal")


@implementer(IMammoth)
class Mammoth(Contained, grok.testing.Model):
    grok.testing.protect_get(grok.Public, 'name', 'size')
    grok.testing.protect_set(grok.Public, 'name', 'size')

    def __init__(self, name='', size=''):
        self.name = name
        self.size = size


class Index(grok.View):
    grok.context(Mammoth)

    def render(self):
        return 'Hi, my name is {}, and I\'m "{}"'.format(self.context.name,
                                                         self.context.size)


class AddMammoth(grok.AddForm):
    grok.context(Zoo)

    form_fields = grok.AutoFields(Mammoth)

    @grok.action('Add entry')
    def add(self, **data):
        # pass data into Mammoth constructor
        self.context['manfred'] = manfred = Mammoth(**data)
        self.redirect(self.url(manfred))


class AddMammothApplyData(AddMammoth):

    @grok.action('Add entry')
    def add(self, **data):
        # instantiate Mammoth and then use self.applyData()
        self.context['ellie'] = ellie = Mammoth()
        self.applyData(ellie, **data)
        self.redirect(self.url(ellie))
