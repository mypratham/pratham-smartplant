"""
  >>> from zope.publisher.browser import TestRequest
  >>> context = FooContext()
  >>> request = TestRequest()
  >>> view = WithFooTemplate(context, request)
  >>> print(view())
  Foo Template.

  >>> view = WithFooTemplateNoExists(context, request)
  >>> view()
  Traceback (most recent call last):
    ...
  FileNotFoundError: [Errno 2] No such file or directory: '...templates/nothere.cpt'

  >>> view = NonGrokViewWithTemplate(context, request)
  >>> print(view())
  Foo Template.

  >>> view = NonGrokViewWithTemplateNoExists(context, request)
  >>> view()
  Traceback (most recent call last):
    ...
  FileNotFoundError: [Errno 2] No such file or directory: '...templates/nothere.cpt'

"""  # noqa: E501 line too long
import grokcore.component
import grokcore.component.interfaces
import grokcore.view
import zope.interface

from grokcore.chameleon.components import ChameleonPageTemplateFile
from grokcore.chameleon.components import PageTemplateFile


@zope.interface.implementer(grokcore.component.interfaces.IContext)
class FooContext:
    pass


class WithFooTemplate(grokcore.view.View):
    grokcore.component.context(zope.interface.Interface)

    template = ChameleonPageTemplateFile('templates/foo.cpt')


class WithFooTemplateNoExists(WithFooTemplate):
    template = ChameleonPageTemplateFile('templates/nothere.cpt')


class NonGrokViewWithTemplate:
    template = PageTemplateFile('templates/foo.cpt')

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        return self.template()


class NonGrokViewWithTemplateNoExists(NonGrokViewWithTemplate):
    template = PageTemplateFile('templates/nothere.cpt')
