# Author: Eric Kow
# License: CeCILL-B (French BSD3-like)

"""
Rename an annotation
"""

from __future__ import print_function
import sys

from educe.stac.util.args import\
    add_usual_input_args, add_usual_output_args,\
    read_corpus, get_output_dir, announce_output_dir,\
    anno_id
from educe.stac.util.doc import compute_renames, evil_set_id
from educe.stac.util.glozz import anno_id_from_tuple, anno_id_to_tuple
from educe.stac.util.output import save_document


def _has_named_annotation(target, doc):
    """
    Return True if the given document has the target annotation
    """
    return any(anno_id_to_tuple(x.local_id()) == target
               for x in  doc.annotations())


def _get_target(args, source, corpus):
    """
    Return either the explicitly specified target from the command line
    or a new one that we computed by looking at the current corpus.
    Check for collisions while we're at it
    """
    if args.target:
        has_collision = any(_has_named_annotation(args.target, doc)
                            for doc in corpus.values())
        if has_collision:
            sys.exit("Can't rename! " +
                     "We already have annotation(s) with ID %s" % args.target)
        else:
            return args.target
    else:
        # generate a new name
        renames = compute_renames(corpus, corpus)
        source_author, source_date = source
        target_author = source_author
        target_date = renames[source_author][source_date]
        return (target_author, target_date)


def _rename_in_doc(source, target, doc):
    """
    Rename all annotations with the given source id in the given document

    NB: modifies doc
    """
    matches = [x for x in doc.annotations() if
               anno_id_to_tuple(x.local_id()) == source]
    pretty_source = anno_id_from_tuple(source)
    pretty_target = anno_id_from_tuple(target)
    target_author, target_date = target

    def replace_pointer(pointers):
        "Given annotation id, return copy with s/src/tgt/"
        return [pretty_target if ptr == pretty_source else ptr
                for ptr in pointers]

    if not matches:
        sys.exit("No annotations found with id %s" % pretty_source)
    elif len(matches) > 1:
        sys.exit("Huh?! More than one annotation with id %s" % pretty_source)
    evil_set_id(matches[0], target_author, target_date)
    for anno in doc.relations:
        if anno.span.t1 == pretty_source:
            anno.span.t1 = pretty_target
        if anno.span.t2 == pretty_source:
            anno.span.t2 = pretty_target
    for anno in doc.schemas:
        anno.units = replace_pointer(anno.units)
        anno.relations = replace_pointer(anno.relations)
        anno.schemas = replace_pointer(anno.schemas)

# ---------------------------------------------------------------------
# command and options
# ---------------------------------------------------------------------

NAME = 'rename'


def config_argparser(parser):
    """
    Subcommand flags.

    You should create and pass in the subparser to which the flags
    are to be added.
    """
    add_usual_input_args(parser, doc_subdoc_required=True)
    add_usual_output_args(parser, default_overwrite=True)
    parser.add_argument('--stage', metavar='STAGE',
                        choices=['discourse', 'units', 'unannotated'])
    parser.add_argument('--annotator', metavar='STRING')
    parser.add_argument('--source', type=anno_id, metavar='ANNO_ID',
                        required=True,
                        help='id to rename (eg. kowey_398190)')
    parser.add_argument('--target', type=anno_id, metavar='ANNO_ID',
                        help='id to rename to (default: autogenerated)')
    parser.set_defaults(func=main)


def main(args):
    """
    Subcommand main.

    You shouldn't need to call this yourself if you're using
    `config_argparser`
    """
    if args.stage:
        if args.stage != 'unannotated' and not args.annotator:
            sys.exit("--annotator is required unless --stage is unannotated")
        elif args.stage == 'unannotated' and args.annotator:
            sys.exit("--annotator is forbidden if --stage is unannotated")
    output_dir = get_output_dir(args, default_overwrite=True)
    corpus = read_corpus(args, verbose=True)

    source = args.source
    target = _get_target(args, source, corpus)

    for k in corpus:
        print(k)
        doc = corpus[k]
        _rename_in_doc(source, target, doc)
        save_document(output_dir, k, doc)
    pretty_source = anno_id_from_tuple(source)
    pretty_target = anno_id_from_tuple(target)
    print("Renamed from %s to %s" % (pretty_source, pretty_target),
          file=sys.stderr)
    announce_output_dir(output_dir)
