#!/usr/bin/python
#	vim:fileencoding=utf-8
# (C) 2010 Michał Górny <gentoo@mgorny.alt.pl>
# Released under the terms of the 3-clause BSD license.

import codecs, glob, os.path

class PackageFileSet(object):
	class PackageFile(list):
		class Whitespace(object):
			def __init__(self, l):
				self.data = l

			def __nonzero__(self):
				return True

			def toString(self):
				return self.data

			@property
			def modified(self):
				return False

			@modified.setter
			def modified(self, newval):
				pass

		class PackageEntry(object):
			class InvalidPackageEntry(Exception):
				pass

			class PackageFlag(object):
				def __init__(self, s):
					if s[0] in ('-', '+'):
						self.modifier = s[0]
						self.name = s[1:]
					else:
						self.modifier = ''
						self.name = s

				def __lt__(self, other):
					return self.name < other.name

				def toString(self):
					return '%s%s' % (self.modifier, self.name)

			def __init__(self, l):
				sl = l.split()
				if not sl or sl[0].startswith('#'): # whitespace
					raise self.InvalidPackageEntry()

				self.as_str = l
				self.modified = False
				self.package = sl.pop(0)
				self.flags = [self.PackageFlag(x) for x in sl]

			def toString(self):
				if not self.modified:
					return self.as_str
				else:
					return ' '.join([self.package] + \
							[x.toString() for x in self.flags]) + '\n'

			def append(self, flag):
				if not isinstance(flag, self.PackageFlag):
					flag = self.PackageFlag(flag)
				self.flags.append(flag)
				self.modified = True
				return flag

			def remove(self, flag):
				self.flags.remove(flag)
				self.modified = True

			def sort(self):
				self.flags.sort()
				self.modified = True

			def __lt__(self, other):
				return self.package < other.package

			def __iter__(self):
				""" Iterate over all flags in the entry. """
				for f in reversed(self.flags):
					yield f

			def __len__(self):
				return len(self.flags)

			def __getitem__(self, flag):
				""" Iterate over occurences of flag in the entry,
					returning them in the order of occurence. """
				for f in self:
					if flag == f.name:
						yield f

			def __delitem__(self, flag):
				""" Remove all occurences of a flag. """
				flags = []
				for f in self.flags:
					if flag == f.name:
						flags.append(f)
				for f in flags:
					self.flags.remove(f)

				self.modified = True

		def __init__(self, path):
			self.path = path
			# _modified is for when items are removed
			self._modified = False
			if not os.path.exists(path):
				return
			f = codecs.open(path, 'r', 'utf8')
			for l in f:
				try:
					e = self.PackageEntry(l)
				except self.PackageEntry.InvalidPackageEntry:
					e = self.Whitespace(l)
				self.append(e)
			f.close()

		def sort(self):
			# we have to drop all the whitespace before sorting
			for e in list(self):
				if isinstance(e, self.Whitespace):
					self.remove(e)

			list.sort(self)
			self.modified = True

		@property
		def modified(self):
			if self._modified:
				return True
			for e in self:
				if e.modified:
					return True
			return False

		@modified.setter
		def modified(self, val):
			self._modified = val

		def write(self):
			if not self.modified:
				return

			f = codecs.open(self.path, 'w', 'utf8')
			for l in self:
				if not l.modified or l:
					f.write(l.toString())
			f.close()

			for e in self:
				e.modified = False
			self.modified = False

	def __init__(self, path):
		self._path = path
		self._files = []

	@property
	def files(self):
		if not self._files:
			self.read()
		return self._files

	def read(self):
		if self._files:
			return

		if os.path.isdir(self._path):
			files = sorted(glob.glob(os.path.join(self._path, '*')))
			if not files:
				files = [os.path.join(self._path, 'flaggie')]
		else:
			files = [self._path]

		for path in files:
			self._files.append(self.PackageFile(path))

	def write(self):
		if not self._files:
			return

		for f in self._files:
			f.write()
			del f
		self._files = []

	def append(self, pkg):
		f = self.files[-1]
		if not isinstance(pkg, f.PackageEntry):
			pkg = f.PackageEntry(pkg)
		pkg.modified = True
		f.append(pkg)
		return pkg

	def remove(self, pkg):
		found = False
		for f in self.files:
			try:
				f.remove(pkg)
			except ValueError:
				pass
			else:
				f.modified = True
				found = True
		if not found:
			raise ValueError('%s not found in package.* files.' % pkg)

	def sort(self):
		for f in self.files:
			f.sort()

	def __iter__(self):
		""" Iterate over package entries. """
		for f in reversed(self.files):
			for e in reversed(f):
				if isinstance(e, f.PackageEntry):
					yield e

	def __getitem__(self, pkg):
		""" Get package entries for a package in order of effectiveness
			(the last declarations in the file are effective, and those
			will be returned first). """
		for e in self:
			if pkg == e.package:
				yield e

	def __delitem__(self, pkg):
		""" Delete all package entries for a package. """
		for f in self.files:
			entries = []
			for e in f:
				if pkg == e.package:
					entries.append(e)
			for e in entries:
				f.remove(e)
			f.modified = True

class PackageKeywordsFileSet(PackageFileSet):
	def __init__(self, path, dbapi):
		PackageFileSet.__init__(self, path)

		self._defkw = ['~' + x for x \
				in dbapi.settings['ACCEPT_KEYWORDS'].split() \
				if x[0] not in ('~', '-')]

	def read(self, *args):
		if self._files:
			return

		PackageFileSet.read(*((self,) + args))

		# set defaults
		for e in self:
			if not e:
				for f in self._defkw:
					e.append(f)
				e.modified = False

class PackageFiles(object):
	def __init__(self, basedir, dbapi):
		p = lambda x: os.path.join(basedir, x)
		self.files = {
			'use': PackageFileSet(p('package.use')),
			'kw': PackageKeywordsFileSet(p('package.keywords'), dbapi),
			'lic': PackageFileSet(p('package.license'))
		}

	def __getitem__(self, k):
		return self.files[k]

	def __iter__(self):
		return iter(self.files.values())

	def write(self):
		for f in self:
			f.write()
