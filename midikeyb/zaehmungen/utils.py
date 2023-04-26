from math import pow, log10
import json
import re


def db2amp (dBvalue):
    """ convert dB to amplitude (0, 1) """
    return pow(10.0, (0.05 * dBvalue))

def amp2db (amplitude):
    """ convert amp (0, 1) to dB """
    return 20.0 * log10(amplitude)

def linlin(x, x0, x1, y0, y1):
    """
    convert `x` from (x0, x1) to (y0, y1)
    """
    return (x - x0) / (x1 - x0) * (y1 - y0) + y0

def clip(x, minx, maxx):
    if x < minx:
        x = minx
    elif x > maxx:
        x = maxx
    return x

def raise_exception(e):
    raise e

def linspace(start, stop, n):
    """
    pure python implementation of numpy's linspace

    >>> linspace(0, 1, 11)
    [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1]
    >>> len(linspace(0, 1, 10))
    10
    >>> linspace(0, 1, 1)
    1
    >>> linspace(0, 1, 3)
    [0, 0.5, 1]
    """
    if n == 1:
        return [stop]
    out = []
    h = (stop - start) / (n - 1)
    for i in range(n):
        out.append(start + h * i)
    return out

def json_load(path):
    """
    load json, removes all "spurious" elements (comments, trailing commas, etc.)
    """
    s = open(path).read()
    s = json_remove_all(s)
    return json.loads(s)

def json_minify(json, strip_space=True):
    """
    strip comments and remove space from string

    json: a string representing a json object
    """
    tokenizer = re.compile('"|(/\*)|(\*/)|(//)|\n|\r')
    in_string = False
    in_multiline_comment = False
    in_singleline_comment = False
    new_str = []
    from_index = 0
    
    for match in re.finditer(tokenizer, json):
        if not in_multiline_comment and not in_singleline_comment:
            tmp2 = json[from_index:match.start()]
            if not in_string and strip_space:
                # replace only white space defined in standard
                tmp2 = re.sub('[ \t\n\r]*','',tmp2)
            new_str.append(tmp2)
            
        from_index = match.end()
        
        if match.group() == '"' and not in_multiline_comment and not in_singleline_comment:
            escaped = re.search('(\\\\)*$',json[:match.start()])
            if not in_string or escaped is None or len(escaped.group()) % 2 == 0:
                # start of string with ", or unescaped " character found to end string
                in_string = not in_string
            from_index -= 1   # include " character in next catch          
        elif (match.group() == '/*' and
              not in_string and
              not in_multiline_comment and
              not in_singleline_comment):
            in_multiline_comment = True
        elif (match.group() == '*/' and
              not in_string and
              in_multiline_comment and
              not in_singleline_comment):
            in_multiline_comment = False
        elif (match.group() == '//' and
              not in_string and
              not in_multiline_comment and
              not in_singleline_comment):
            in_singleline_comment = True
        elif ((match.group() == '\n' or match.group() == '\r') and
              not in_string and
              not in_multiline_comment and
              in_singleline_comment):
            in_singleline_comment = False
        elif (not in_multiline_comment and
              not in_singleline_comment and
              (match.group() not in ['\n','\r',' ','\t'] or not strip_space)):
            new_str.append(match.group())
    
    new_str.append(json[from_index:])
    return ''.join(new_str)


def _comments_replacer(match):
    s = match.group(0)
    return "" if s[0] == '/' else s
    

def json_remove_comments(json_like: str):
    """
    Removes C-style comments from *json_like* and returns the result.  Example::
        >>> test_json = '''\
        {
            "foo": "bar", // This is a single-line comment
            "baz": "blah" /* Multi-line
            Comment */
        }'''
        >>> remove_comments('{"foo":"bar","baz":"blah",}')
        '{\n    "foo":"bar",\n    "baz":"blah"\n}'
    """
    comments_re = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE
    )
    
    return comments_re.sub(_comments_replacer, json_like)


def json_remove_trailing_commas(json_like: str):
    """
    Removes trailing commas from *json_like* and returns the result.  Example::
        >>> remove_trailing_commas('{"foo":"bar","baz":["blah",],}')
        '{"foo":"bar","baz":["blah"]}'
    """
    trailing_object_commas_re = re.compile(
        r'(,)\s*}(?=([^"\\]*(\\.|"([^"\\]*\\.)*[^"\\]*"))*[^"]*$)')
    trailing_array_commas_re = re.compile(
        r'(,)\s*\](?=([^"\\]*(\\.|"([^"\\]*\\.)*[^"\\]*"))*[^"]*$)')
    # Fix objects {} first
    objects_fixed = trailing_object_commas_re.sub("}", json_like)
    # Now fix arrays/lists [] and return the result
    return trailing_array_commas_re.sub("]", objects_fixed)


def json_remove_all(json_like: str):
    """
    Remove comments and trailing commas
    """
    pipe = [json_remove_comments, json_remove_trailing_commas]
    s = json_like
    for func in pipe:
        s = func(s)
    return s
