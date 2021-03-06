# Author: Eric Kow
# License: CeCILL-B (French BSD3-like)

"""
Inject annotations from an augmented corpus into the original.

We only read the unannotated stage of the augmented corpus.
It is augmented in the sense that it may contain extra bits
of text interspersed with the original.
"""

from __future__ import print_function
import copy
import difflib
import sys

from educe.stac.oneoff.weave import\
    (check_matches,
     compute_updates,
     shift_span)
from educe.stac.util.args import\
    (add_usual_input_args, add_usual_output_args,
     get_output_dir, announce_output_dir,
     read_corpus_with_unannotated)
from educe.stac.util.output import save_document
from educe.stac.util.doc import\
    (evil_set_text,
     compute_renames, rename_ids,
     unannotated_key)
from educe.util import mk_is_interesting
import educe.stac


def _preview_anno(doc, anno, max_width=50):
    """Short text representation of an annotation"""
    span = anno.text_span()
    text = doc.text(span)
    if len(text) > max_width:
        snippet = text[:max_width] + '...'
    else:
        snippet = text
    template = '{ty} {span} [{snippet}]'
    return template.format(ty=anno.type,
                           span=span,
                           snippet=snippet)


def _maybe_warn(warning, doc, annos):
    """Emit a warning about a potentially problematic group of annotations
    """
    if annos:
        oops = 'WARNING: ' + warning + ':\n'
        oops += '\n'.join(['    {}'.format(_preview_anno(doc, x))
                           for x in annos])
        print(oops, file=sys.stderr)


def _hollow_out_nonplayer_text(src_doc):
    """Return a version of the source text where all characters in nonplayer
    turns are replaced with a nonsense char (tab).

    Notes
    -----
    We use difflib's SequenceMatcher to compare the original (but annotated)
    corpus against the augmented corpus containing nonplayer turns. This
    gives us the ability to shift annotation spans into the appropriate
    place within the augmented corpus. By rights the diff should yield only
    inserts (of the nonplayer turns). But if the inserted text should happen
    to have the same sorts of substrings as you might find in the rest of
    corpus, the diff algorithm can be fooled.
    """
    # docstring followup:
    #
    # That said, since we know exactly what things we expect to have inserted,
    # it's not clear to me why we are using diff and not just computing the
    # shifts off the nonplayer turns. Was I being lazy? Did I just not work
    # out this was possible? Was I trying to be robust? It could also have
    # something to do with managing the extra bits of whitespace around the
    # new nonplayer turns.  To simplify...

    # we can't use the API one until we update it to account for the
    # fancy new identifiers
    np_spans = [x.text_span() for x in src_doc.units
                if x.type == 'NonplayerTurn']

    # merge consecutive nonplayer turns
    current = None
    merged_np_spans = []
    for span in sorted(np_spans):
        if not current:
            current = span
            continue
        elif span.char_start == current.char_end + 1:
            current = current.merge(span)
        else:
            merged_np_spans.append(current)
            current = span
    merged_np_spans.append(current)

    orig = src_doc.text()
    res = ''
    last = 0
    for span in merged_np_spans:
        res += orig[last:span.char_start]
        res += '\t' * (span.char_end - span.char_start)
        last = span.char_end
    res += orig[last:]
    return res


def _weave_docs(renames, src_doc, tgt_doc):
    """Return a deep copy of the target document with combined
    annotations from both the original source and target
    """

    if renames:
        src_doc = rename_ids(renames, src_doc)
    res_doc = copy.deepcopy(tgt_doc)
    src_text = src_doc.text()
    tgt_text = tgt_doc.text()

    matcher = difflib.SequenceMatcher(isjunk=None,
                                      a=_hollow_out_nonplayer_text(src_doc),
                                      b=tgt_text,
                                      autojunk=False)
    matches = matcher.get_matching_blocks()
    check_matches(tgt_doc, matches)

    # we have to compute the updates on the basis of the result
    # doc because we want to preserve things like relation and
    # cdu pointers (which have been deep copied from original)
    updates = compute_updates(src_doc, res_doc, matches)

    structural_tgt_only = [x for x in updates.abnormal_tgt_only if
                           educe.stac.is_structure(x)]
    unknown_tgt_only = [x for x in updates.abnormal_tgt_only if
                        x not in structural_tgt_only and
                        not educe.stac.is_resource(x) and
                        not educe.stac.is_preference(x)]

    # the most important change: update the spans for all current
    # target annotations
    for tgt_anno in res_doc.units:
        tgt_anno.span = shift_span(tgt_anno.span, updates)
    evil_set_text(res_doc, src_text)

    for src_anno in updates.expected_src_only:
        res_doc.units.append(src_anno)

    _maybe_warn(('copying over the following source annotations, which '
                 'should have matches on the target side but do not'),
                src_doc, updates.abnormal_src_only)
    for src_anno in updates.abnormal_src_only:
        res_doc.units.append(src_anno)

    _maybe_warn(('copying over the following target annotations, which '
                 'should have matches on the source side but do not'),
                res_doc, unknown_tgt_only)
    # nothing to do here as we've already done the copying

    _maybe_warn('ignoring the following target annotations which '
                'do not have equivalents on the source side but which we '
                'half-expect because of their structural nature',
                res_doc, structural_tgt_only)
    for tgt_anno in structural_tgt_only:
        res_doc.units.remove(tgt_anno)

    return res_doc


# ---------------------------------------------------------------------
# command and options
# ---------------------------------------------------------------------

def config_argparser(parser):
    """
    Subcommand flags.

    You should create and pass in the subparser to which the flags
    are to be added.
    """
    parser.add_argument('augmented', metavar='DIR',
                        help='augmented corpus dir')
    add_usual_input_args(parser,
                         help_suffix='to insert into')
    add_usual_output_args(parser)
    parser.set_defaults(func=main)


def read_augmented_corpus(args, verbose=True):
    """
    Read the unannotated stage of the augmented corpus
    """
    aug_args = copy.copy(args)
    aug_args.annotator = None
    preselection = {'stage': ['unannotated']}
    is_interesting = mk_is_interesting(aug_args,
                                       preselected=preselection)
    reader = educe.stac.Reader(args.augmented)
    anno_files = reader.filter(reader.files(), is_interesting)
    return reader.slurp(anno_files, verbose)


def main(args):
    """
    Subcommand main.

    You shouldn't need to call this yourself if you're using
    `config_argparser`
    """
    output_dir = get_output_dir(args)
    augmented = read_augmented_corpus(args)
    corpus = read_corpus_with_unannotated(args)
    renames = compute_renames(corpus, augmented)
    for key in corpus:
        ukey = unannotated_key(key)
        new_tgt_doc = _weave_docs(renames, augmented[ukey], corpus[key])
        save_document(output_dir, key, new_tgt_doc)
    announce_output_dir(output_dir)
