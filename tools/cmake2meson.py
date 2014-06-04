#!/usr/bin/python3

# Copyright 2014 Jussi Pakkanen

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys, os
import re

class Token:
    def __init__(self, tid, value):
        self.tid = tid
        self.value = value
        self.lineno = 0
        self.colno = 0

class Statement():
    def __init__(self, name, args):
        self.name = name
        self.args = args

class Lexer:
    def __init__(self):
        self.token_specification = [
            # Need to be sorted longest to shortest.
            ('ignore', re.compile(r'[ \t]')),
            ('string', re.compile(r'"([^\\]|(\\.))*?"', re.M)),
            ('varexp', re.compile(r'\${[-_0-9a-z/A-Z.]+}')),
            ('id', re.compile('''[,-><${}=+_0-9a-z/A-Z@.*]+''')),
            ('eol', re.compile(r'\n')),
            ('comment', re.compile(r'\#.*')),
            ('lparen', re.compile(r'\(')),
            ('rparen', re.compile(r'\)')),
        ]

    def lex(self, code):
        lineno = 1
        line_start = 0
        loc = 0;
        col = 0
        while(loc < len(code)):
            matched = False
            for (tid, reg) in self.token_specification:
                mo = reg.match(code, loc)
                if mo:
                    col = mo.start()-line_start
                    matched = True
                    loc = mo.end()
                    match_text = mo.group()
                    if tid == 'ignore':
                        continue
                    if tid == 'comment':
                        yield(Token('comment', match_text))
                    elif tid == 'lparen':
                        yield(Token('lparen', '('))
                    elif tid == 'rparen':
                        yield(Token('rparen', ')'))
                    elif tid == 'string':
                        yield(Token('string', match_text[1:-1]))
                    elif tid == 'id':
                        yield(Token('id', match_text))
                    elif tid == 'eol':
                        #yield('eol')
                        lineno += 1
                        col = 1
                        line_start = mo.end()
                        pass
                    elif tid == 'varexp':
                        yield(Token('varexp', match_text[2:-1]))
                    else:
                        raise RuntimeError('Wharrgarbl')
                    break
            if not matched:
                raise RuntimeError('Lexer got confused line %d column %d' % (lineno, col))

class Parser():
    def __init__(self, code):
        self.stream = Lexer().lex(code)
        self.getsym()

    def getsym(self):
        try:
            self.current = next(self.stream)
        except StopIteration:
            self.current = Token('eof', '')

    def accept(self, s):
        if self.current.tid == s:
            self.getsym()
            return True
        return False

    def expect(self, s):
        if self.accept(s):
            return True
        raise RuntimeError('Expecting %s got %s.' % (s, self.current.tid), self.current.lineno, self.current.colno)

    def statement(self):
        cur = self.current
        if self.accept('comment'):
            return Statement('_', [cur.value])
        self.accept('id')
        self.expect('lparen')
        args = self.arguments()
        self.expect('rparen')
        return Statement(cur.value, args)

    def arguments(self):
        args = []
        if self.accept('lparen'):
            args.append(self.arguments())
            self.expect('rparen')
        arg = self.current
        if self.accept('string') or self.accept('varexp') or\
        self.accept('id'):
            args.append(arg)
            rest = self.arguments()
            args += rest
        return args

    def parse(self):
        while not self.accept('eof'):
            yield(self.statement())

class Converter:
    ignored_funcs = {'cmake_minimum_required' : True,
                     'enable_testing' : True,
                     'include' : True}
    def __init__(self, cmake_root):
        self.cmake_root = cmake_root
        self.indent_unit = '  '
        self.indent_level = 0

    def convert_args(self, args):
        res = []
        for i in args:
            if i.tid == 'id':
                res.append("'%s'" % i.value)
            elif i.tid == 'varexp':
                res.append('%s' % i.value)
            elif i.tid == 'string':
                res.append("'%s'" % i.value)
            else:
                print(i)
                raise RuntimeError('Unknown arg type.')
        if len(res) > 1:
            return '[' + ', '.join(res) + ']'
        if len(res) == 1:
            return res[0]
        return ''

    def write_entry(self, outfile, t):
        if t.name in Converter.ignored_funcs:
            return

        indent = self.indent_level*self.indent_unit
        if t.name == '_':
            line = t.args[0]
        elif t.name == 'add_subdirectory':
            line = "subdir('" + t.args[0].value + "')"
        elif t.name == 'pkg_search_module' or t.name == 'pkg_search_modules':
            varname = t.args[0].value.lower()
            mods = ["dependency('%s')" % i.value for i in t.args[1:]]
            if len(mods) == 1:
                line = '%s = %s' % (varname, mods[0])
            else:
                line = '%s = [%s]' % (varname, ', '.join(["'%s'" % i for i in mods]))
        elif t.name == 'find_package':
            line = '%s_dep = dependency(%s)' % (t.args[0].value, t.args[0].value)
        elif t.name == 'project':
            pname = t.args[0].value
            args = [pname]
            for l in t.args[1:]:
                l = l.value.lower()
                if l == 'cxx':
                    l = 'cpp'
                args.append(l)
            args = ["'%s'" % i for i in args]
            line = 'project(' + ', '.join(args) + ')'
        elif t.name == 'set':
            varname = t.args[0].value.lower()
            line = '%s = %s\n' % (varname, self.convert_args(t.args[1:]))
        else:
            line = '''# %s''' % t.name
        outfile.write(indent)
        outfile.write(line)
        if not(line.endswith('\n')):
            outfile.write('\n')

    def convert(self, subdir=''):
        if subdir == '':
            subdir = self.cmake_root
        cfile = os.path.join(subdir, 'CMakeLists.txt')
        try:
            cmakecode = open(cfile).read()
        except FileNotFoundError:
            print('\nWarning: No CMakeLists.txt in', subdir, '\n')
            return
        p = Parser(cmakecode)
        outfile = open(os.path.join(subdir, 'meson.build'), 'w')
        for t in p.parse():
            if t.name == 'add_subdirectory':
                #print('\nRecursing to subdir', os.path.join(self.cmake_root, t.args[0].value), '\n')
                self.convert(os.path.join(subdir, t.args[0].value))
                #print('\nReturning to', self.cmake_root, '\n')
            self.write_entry(outfile, t)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(sys.argv[0], '<CMake project root>')
        sys.exit(1)
    c = Converter(sys.argv[1])
    c.convert()