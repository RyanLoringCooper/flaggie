#!/usr/bin/python
# vim:fileencoding=utf-8:noet
# (C) 2017 Michał Górny <gentoo@mgorny.alt.pl>
# Released under the terms of the 2-clause BSD license.

import os
import os.path

from portage.dep import use_reduce
from portage.util import grabdict, grabfile
from portage.versions import best


def grab_use_desc(path, prefix=''):
	flags = {}
	try:
		f = open(path, 'r', encoding="utf-8")
	except IOError:
		pass
	else:
		for l in f:
			ll = l.split(' - ', 1)
			if len(ll) > 1:
				flags[prefix + ll[0]] = ll[1].strip()
		f.close()

	return flags


class DBAPICache(object):
	aux_key = None

	def __init__(self, dbapi):
		if not self.aux_key:
			raise AssertionError('DBAPICache.aux_key needs to be overriden.')
		self.dbapi = dbapi
		self.cache = {}
		self.effective_cache = {}

	@property
	def glob(self):
		raise AssertionError('DBAPICache.glob() needs to be overriden.')

	def _aux_parse(self, arg):
		return arg.split()

	def __getitem__(self, k):
		if k not in self.cache:
			flags = set()
			# get widest match possible to make sure we do not
			# complain without a reason
			for p in self.dbapi.xmatch('match-all', k):
				flags.update(self._aux_parse(self.dbapi.aux_get(p,
						(self.aux_key,))[0]))
			self.cache[k] = frozenset(flags)
		return self.cache[k]

	def get_effective(self, k):
		if k not in self.effective_cache:
			pkgs = self.dbapi.xmatch('match-all', k)
			if pkgs:
				flags = self._aux_parse(self.dbapi.aux_get(
					best(pkgs), (self.aux_key,))[0])
			else:
				flags = ()
			self.effective_cache[k] = frozenset(flags)
		return self.effective_cache[k]


class FlagCache(DBAPICache):
	aux_key = 'IUSE'

	def __init__(self, dbapi):
		DBAPICache.__init__(self, dbapi)
		self.use_expand_vars = dbapi.settings.get('USE_EXPAND', '').split()

	@property
	def glob(self):
		if None not in self.cache:
			flags = set()
			for r in self.dbapi.porttrees:
				flags.update(grab_use_desc(os.path.join(r, 'profiles', 'use.desc')))
				for k in self.use_expand_vars:
					flags.update(grab_use_desc(
						os.path.join(r, 'profiles', 'desc', '%s.desc' % k.lower()),
						prefix=('%s_' % k.lower())))
			self.cache[None] = frozenset(flags)

		return self.cache[None]

	def _aux_parse(self, arg):
		return (x.lstrip('+-') for x in arg.split())


class KeywordCache(DBAPICache):
	aux_key = 'KEYWORDS'

	@property
	def glob(self):
		if None not in self.cache:
			kws = set()
			for r in self.dbapi.porttrees:
				kws.update(grabfile(os.path.join(r, 'profiles', 'arch.list')))
			kws.update(['~%s' % x for x in kws], ('*', '**', '~*'))

			# and the ** special keyword
			self.cache[None] = frozenset(kws)

		return self.cache[None]

	def _aux_parse(self, arg):
		kw = [x for x in arg.split() if not x.startswith('-')]
		kw.extend(('*', '**'))
		return kw


class LicenseCache(DBAPICache):
	aux_key = 'LICENSE'
	_groupcache = None

	@property
	def groups(self):
		if self._groupcache is None:
			self._groupcache = {}
			for r in self.dbapi.porttrees:
				path = os.path.join(r, 'profiles', 'license_groups')
				for k, v in grabdict(path).items():
					k = '@%s' % k
					if k not in self._groupcache:
						self._groupcache[k] = set()
					self._groupcache[k].update(v)

		return self._groupcache

	@property
	def glob(self):
		if None not in self.cache:
			lic = set()
			for r in self.dbapi.porttrees:
				try:
					lic.update(os.listdir(os.path.join(r, 'licenses')))
				except OSError:
					pass
				lic.update(self.groups)

			lic.discard('CVS')
			self.cache[None] = frozenset(lic)

		return self.cache[None]

	def _aux_parse(self, arg):
		try:
			lic = use_reduce(arg, matchall=True, flat=True)
		except TypeError:  # portage-2.1.8 compat
			from portage.dep import paren_reduce
			lic = use_reduce(paren_reduce(arg, tokenize=True),
					matchall=True)

		lic = set(lic)
		lic.discard('||')
		lic.update(k for k, v in self.groups.items() if lic & v)
		return lic


class EnvCache(object):
	def __init__(self, dbapi):
		out = set()
		path = os.path.join(os.environ.get('PORTAGE_CONFIGROOT', '/'),
				'etc', 'portage', 'env')
		for parent, dirs, files in os.walk(path):
			out.update(os.path.relpath(os.path.join(parent, x), path) for x in files)
		self.cache = frozenset(out)

	@property
	def glob(self):
		return frozenset()

	def __getitem__(self, k):
		return self.cache


class Caches(object):
	def __init__(self, dbapi):
		self.caches = {
			'use': FlagCache(dbapi),
			'kw': KeywordCache(dbapi),
			'lic': LicenseCache(dbapi),
			'env': EnvCache(dbapi)
		}

	def glob_whatis(self, arg, restrict=None):
		if not restrict:
			restrict = frozenset(self.caches)
		ret = set()
		for k in self.caches:
			if k in restrict and arg in self.caches[k].glob:
				ret.add(k)
		return ret

	def whatis(self, arg, pkg, restrict=None):
		if not restrict:
			restrict = frozenset(self.caches)
		ret = set()
		for k in self.caches:
			if k in restrict and arg in self.caches[k][pkg]:
				ret.add(k)
		return ret

	def describe(self, ns):
		if ns == 'use':
			return 'flag'
		elif ns == 'kw':
			return 'keyword'
		elif ns == 'lic':
			return 'license'
		elif ns == 'env':
			return 'env file'
		else:
			raise AssertionError('Unexpected ns %s' % ns)

	def __iter__(self):
		return iter(self.caches)

	def __getitem__(self, k):
		return self.caches[k]
