# -*- coding: utf-8 -*-

import itertools
import logging


try:
    from collections import OrderedDict
except ImportError:  # pragma: no cover
    # if on python 2.6
    from ordereddict import OrderedDict

class LayeredConfig(object):
    def __init__(self, *sources, **kwargs):
        """Creates a config object from zero or more sources.

        If no sources are given, the config object is blank, but you
        can still set values and read them back later.

        Provides unified access to a nested set of configuration
        parameters. The source of these parameters a config file
        (using .ini-file style syntax), command line parameters, and
        default settings embedded in code. Command line parameters
        override configuration file parameters, which in turn override
        default settings in code (hence **Layered** Config).

        Configuration parameters are accessed as regular object
        attributes, not dict-style key/value pairs.  Configuration
        parameter names should therefore be regular python identifiers
        (i.e. only consist of alphanumerical chars and '_').

        Configuration parameter values can be typed (strings,
        integers, booleans, dates, lists...).  Even though ini-style
        config files and command line parameters are by themselves
        non-typed, by specifying default settings in code, parameters
        from a config file or the commamd line can be typed.

        Example::
 
            >>> defaults = {'parameter': 'foo', 'other': 'default'}
            >>> dir = tempfile.mkdtemp()
            >>> inifile = dir + os.sep + "test.ini"
            >>> with open(inifile, "w") as fp:
            ...     res = fp.write("[__root__]\\nparameter = bar")
            >>> argv = ['--parameter=baz']
            >>> conf = LayeredConfig(Defaults(defaults), INIFile(inifile), Commandline(argv))
            >>> conf.parameter == 'baz'
            True
            >>> conf.other == 'default'
            True
            >>> conf.parameter = 'changed'
            >>> conf.other = 'also changed'
            >>> LayeredConfig.write(conf)
            >>> with open(inifile) as fp:
            ...     res = fp.read()
            >>> res == '[__root__]\\nparameter = changed\\nother = also changed\\n\\n'
            True
            >>> os.unlink(inifile)
            >>> os.rmdir(dir)
 
        :param cascade: If an attempt to get a non-existing parameter
                        on a sub (nested) configuration object should
                        attempt to get the parameter on the parent
                        config object. ``False`` by default,
        :type cascade: bool
        :param writable: Whether configuration values should be mutable.
                         ``True`` by default. This does not affect
                         :py:meth:`~Layeredconfig.set`. 
        :type writable: bool
        """
        self._sources = sources
        self._subsections = OrderedDict()
        self._cascade = kwargs.get('cascade', False)
        self._writable = kwargs.get('writable', True)
        self._parent = None
        self._sectionkey = None

        # Each source may have any number of named subsections. We
        # create a LayeredConfig object for each name, and stuff all
        # matching subections from each of our sources in it.
        #
        # 1. find all names
        sectionkeys = []
        for src in self._sources:
            try:
                for k in src.subsections():
                    if k not in sectionkeys:
                        sectionkeys.append(k)
            except AttributeError:  # possibly others, or all
                # we couldn't get any subsections for source, perhaps
                # because it's an "empty" source. Well, that's ok.
                pass
                

        for k in sectionkeys:
            # 2. find all subsections in all of our sources
            s = []
            for src in self._sources:
                if k in list(src.subsections()):
                    s.append(src.subsection(k))
                else:
                    # create an "empty" subsection object. It's
                    # imported that all the LayeredConfig objects in a
                    # tree have the exact same set of
                    # ConfigSource-derived types.
                    # print("creating empty %s" % src.__class__.__name__)
                    s.append(src.__class__(parent=src,
                                           identifier=src.identifier,
                                           writable=src.writable,
                                           cascade=self._cascade))
            # 3. create a LayeredConfig object for the subsection
            c = LayeredConfig(*s,
                              cascade=self._cascade,
                              writable=self._writable)
            c._sectionkey = k
            c._parent = self
            self._subsections[k] = c
            
        # cascade=False, writable=True,

    @staticmethod
    def write(config):
        """Configuration parameters can be changed in code. Such changes can
        be written to any write-enabled source (ie. some sort of
        configuration file).
        """
        root = config
        while root._parent:
            root = root._parent

        for source in root._sources:
            if source.writable and source.dirty:
                source.save()

    @staticmethod
    def set(config, key, value, sourceid="defaults"):
        """Sets a value without marking the config file dirty"""
        for source in config._sources:
            if source.identifier == sourceid:
                source.set(key, value)
        # What if no source is found? We silently ignore...

    @staticmethod
    def get(config, key, default=None):
        """Works like dict.get."""
        if hasattr(config, key):
            return getattr(config, key)
        else:
            return default

# These are methods i'd like to implement next
#        
#    @staticmethod
#    def where(config, key):
#        """returns the identifier of a source where a given key is found, or None."""
#        pass
#
#    @staticmethod
#    def dump(config):
#        """Returns the contents of config as a dict."""
#        pass
#
#    @staticmethod
#    def load(config, d):
#        """Recreates a dump()ed config object."""
#        pass

    def __iter__(self):
        l = set()

        iterables = [x.keys() for x in self._sources]

        if self._cascade:
            c = self
            while c._parent:
                iterables.append(c._parent)
                c = c._parent

        for k in itertools.chain(*iterables):
            if k not in l:
                l.add(k)
                yield k

    # FIXME: try to use __getattrib__
    def __getattribute__(self, name):
        if name.startswith("_"):
            return object.__getattribute__(self, name)

        if name in self._subsections:
            return self._subsections[name]

        found = False
        # find the appropriate value in the highest-priority source
        for source in reversed(self._sources):
            # if self._cascade, we must climb the entire chain of
            # .parent objects to be sure.
            done = False
            while not done:
                if source.has(name):
                    found = True
                    done = True  # we found it
                elif self._cascade and source.parent:
                    source = source.parent
                else:
                    done = True  # we didn't find it
            if found:
                break

        if found:
            if source.typed(name):
                return source.get(name)
            else:
                # we need to find a typesource for this value. 
                done = False
                this = self
                while not done:
                    for typesource in reversed(this._sources):
                        if typesource.typed(name):
                            done = True
                            break
                    if not done and self._cascade and this._parent:
                        # Iterate up the parent chain to find it.
                        this = this._parent
                    else:
                        done = True

                if typesource.typed(name):
                    return typesource.typevalue(name, source.get(name))
                else:
                    # we can't type this data, return as-is
                    return source.get(name)
        else:
            if self._cascade and self._parent:
                return self._parent.__getattribute__(name)
        
        raise AttributeError("Configuration key %s doesn't exist" % name)

    def __setattr__(self, name, value):
        # print("__setattribute__ %s to %s" % (name,value))
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return

        # we need to get access to two sources:

        # 1. the highest-priority writable source (regardless of
        #    whether it originally had this value)
        found = False
        for writesource in reversed(self._sources):
            if writesource.writable:
                found = True
                break
        if found:
            writesource.set(name, value)
            writesource.dirty = True
            while writesource.parent:
                writesource = writesource.parent
                writesource.dirty = True

        # 2. the highest-priority source that has this value (typed or
        # not) or contains typing info for it.
        found = False
        for source in reversed(self._sources):
            if source.has(name) or source.typed(name):
                found = True
                break
        if found:
            source.set(name, value)  # regardless of typing
        elif self._cascade and self._parent:
            return self._parent.__setattr__(name, value)
        else:
            raise AttributeError("Configuration key %s doesn't exist" % name)

