import hashlib
import inspect
import logging
from nose.plugins import Plugin
from os.path import join, isfile
from snakefood.find import find_dependencies


try:
    from cpickle import dump, load
except ImportError:
    from pickle import dump, load

log = logging.getLogger(__name__)


def file_hash(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


class Bazinga(Plugin):
    name = 'bazinga'
    hash_file = '.nosebazinga'
    _graph = {}
    _hashes = {}
    _known_graph = {}
    _known_hashes = {}
    _failed_test_modules = set()
    _file_status = {}
    _ignored_files = set()

    def configure(self, options, conf):
        self.hash_file = join(conf.workingDir, self.hash_file)
        if isfile(self.hash_file):
            log.debug("Loading last known hashes and dependency graph")
            with open(self.hash_file, 'r') as f:
                data = load(f)
            self._known_hashes = data['hashes']
            self._known_graph = data['graph']
        Plugin.configure(self, options, conf)

    def afterTest(self, test):
        # None means test never ran, False means failed/err
        if test.passed is False:
            filename = test.address()[0]
            self._failed_test_modules.add(filename)

    def inspectDependencies(self, path):
        try:
            files, _ = find_dependencies(
                path, verbose=False, process_pragmas=False)
            log.debug('Dependencies found for file %s: %s' % (path, files))
        except TypeError as err:
            if path not in self._ignored_files:
                self._ignored_files.add(path)
                log.debug(
                    'Snakefood raised an error (%s) parsing path %s' % (
                        err, path))
                return []

        valid_files = []
        for f in files:
            if not isfile(f) and f not in self._ignored_files:
                self._ignored_files.add(f)
                log.debug('Snakefood returned a wrong path: %s' % (f,))
            elif f in self._ignored_files:
                log.debug('Ignoring built-in module: %s' % (f,))
            else:
                valid_files.append(f)

        return valid_files

    def updateGraph(self, path):
        log.debug(path)
        if path not in self._graph:
            if not self.fileChanged(path) and path in self._known_graph:
                files = self._known_graph[path]
            else:
                files = self.inspectDependencies(path)
            self._graph[path] = files
            for f in files:
                self.updateGraph(f)

    def fileChanged(self, path):
        if path in self._hashes:
            hsh = self._hashes[path]
        else:
            hsh = file_hash(path)
            self._hashes[path] = hsh

        return (
            path not in self._known_hashes or
            hsh != self._known_hashes[path])

    def dependenciesChanged(self, path, parents=None):
        parents = parents or []

        if path in self._file_status:
            return self._file_status[path]
        elif self.fileChanged(path):
            log.debug('File has been modified or failed: %s' % (path,))
            changed = True
        else:
            childs = self._graph[path]
            new_parents = parents + [path]
            changed = any(
                self.dependenciesChanged(f, new_parents) for
                f in childs if
                f not in new_parents)

            if changed:
                log.debug('File depends on modified file: %s' % (path,))

        self._file_status[path] = changed
        return changed

    def finalize(self, result):
        for k, v in self._known_hashes.items():
            self._hashes.setdefault(k, v)

        for k, v in self._known_graph.items():
            self._graph.setdefault(k, v)

        for m in self._failed_test_modules:
            log.debug('Module failed: %s' % (m,))
            self._hashes.pop(m, None)

        with open(self.hash_file, 'w') as f:
            dump({'hashes': self._hashes, 'graph': self._graph}, f)

    def wantModule(self, m):
        source = inspect.getsourcefile(m)
        if source is None:
            return None
        self.updateGraph(source)
        if not self.dependenciesChanged(source):
            log.debug(
                'Ignoring module %s, since no dependencies have changed' % (
                    source,))
            return False

    def wantClass(self, cls):
        source = inspect.getsourcefile(cls)
        if source is None:
            return None
        self.updateGraph(source)
        if not self.dependenciesChanged(source):
            log.debug(
                'Ignoring class %s, since no dependencies have changed' % (
                    source,))
            return False
