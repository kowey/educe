#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Author: Eric Kow
# License: CeCILL-B (French BSD3)

"""
Extract features to CSV files
"""

from __future__ import print_function
import os
import itertools

import educe.corpus
import educe.glozz
import educe.stac
import educe.util

from educe.learning.svmlight_format import dump_svmlight_file
from educe.learning.edu_input_format import (dump_all,
                                             load_labels)
from educe.learning.vocabulary_format import (dump_vocabulary,
                                              load_vocabulary)
from ..args import add_usual_input_args
from ..doc_vectorizer import DocumentCountVectorizer, DocumentLabelExtractor
from educe.rst_dt.corpus import RstDtParser
from educe.rst_dt.ptb import PtbParser


NAME = 'extract'


# ----------------------------------------------------------------------
# options
# ----------------------------------------------------------------------

def config_argparser(parser):
    """
    Subcommand flags.
    """
    add_usual_input_args(parser)
    parser.add_argument('corpus', metavar='DIR',
                        help='Corpus dir (eg. data/pilot)')
    parser.add_argument('ptb', metavar='DIR',
                        help='PTB directory (eg. PTBIII/parsed/wsj)')
    parser.add_argument('output', metavar='DIR',
                        help='Output directory')
    # add flags --doc, --subdoc, etc to allow user to filter on these things
    educe.util.add_corpus_filters(parser,
                                  fields=['doc'])
    parser.add_argument('--verbose', '-v', action='count',
                        default=1)
    parser.add_argument('--quiet', '-q', action='store_const',
                        const=0,
                        dest='verbose')
    parser.add_argument('--parsing', action='store_true',
                        help='Extract features for parsing')
    parser.add_argument('--vocabulary',
                        metavar='FILE',
                        help='Use given vocabulary for feature output '
                        '(when extracting test data, you may want to '
                        'use the feature vocabulary from the training '
                        'set ')
    parser.add_argument('--labels',
                        metavar='FILE',
                        help='Read label set from given feature file '
                        '(important when extracting test data)')

    parser.add_argument('--debug', action='store_true',
                        help='Emit fields used for debugging purposes')
    parser.add_argument('--experimental', action='store_true',
                        help='Enable experimental features '
                             '(currently none)')
    parser.set_defaults(func=main)


# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------

def main(args):
    "main for feature extraction mode"
    # retrieve parameters
    feature_set = args.feature_set
    live = args.parsing

    # RST data
    rst_reader = RstDtParser(args.corpus, args, coarse_rels=True)
    rst_corpus = rst_reader.corpus
    # TODO: change educe.corpus.Reader.slurp*() so that they return an object
    # which contains a *list* of FileIds and a *list* of annotations
    # (see sklearn's Bunch)
    # on creation of these lists, one can impose the list of names to be
    # sorted so that the order in which docs are iterated is guaranteed
    # to be always the same

    # PTB data
    ptb_parser = PtbParser(args.ptb)

    # align EDUs with sentences, tokens and trees from PTB
    def open_plus(doc):
        """Open and fully load a document

        doc is an educe.corpus.FileId
        """
        # create a DocumentPlus
        doc = rst_reader.decode(doc)
        # populate it with layers of info
        # tokens
        doc = ptb_parser.tokenize(doc)
        # syn parses
        doc = ptb_parser.parse(doc)
        # disc segments
        doc = rst_reader.segment(doc)
        # disc parse
        doc = rst_reader.parse(doc)
        # pre-compute the relevant info for each EDU
        doc = doc.align_with_doc_structure()
        # logical order is align with tokens, then align with trees
        # but aligning with trees first for the PTB enables
        # to get proper sentence segmentation
        doc = doc.align_with_trees()
        doc = doc.align_with_tokens()
        # dummy, fallback tokenization if there is no PTB gold or silver
        doc = doc.align_with_raw_words()

        return doc

    # generate DocumentPluses
    # TODO remove sorted() once educe.corpus.Reader is able
    # to iterate over a stable (sorted) list of FileIds
    docs = [open_plus(doc) for doc in sorted(rst_corpus)]
    # instance generator
    instance_generator = lambda doc: doc.all_edu_pairs()

    # extract vectorized samples
    if args.vocabulary is not None:
        vocab = load_vocabulary(args.vocabulary)
        vzer = DocumentCountVectorizer(instance_generator,
                                       feature_set,
                                       vocabulary=vocab)
        X_gen = vzer.transform(docs)
    else:
        vzer = DocumentCountVectorizer(instance_generator,
                                       feature_set,
                                       min_df=5)
        X_gen = vzer.fit_transform(docs)

    # extract class label for each instance
    if live:
        y_gen = itertools.repeat(0)
    elif args.labels is not None:
        labelset = load_labels(args.labels)
        labtor = DocumentLabelExtractor(instance_generator,
                                        labelset=labelset)
        labtor.fit(docs)
        y_gen = labtor.transform(docs)
    else:
        labtor = DocumentLabelExtractor(instance_generator)
        # y_gen = labtor.fit_transform(rst_corpus)
        # fit then transform enables to get classes_ for the dump
        labtor.fit(docs)
        y_gen = labtor.transform(docs)

    # dump instances to files
    if not os.path.exists(args.output):
        os.makedirs(args.output)
    # data file
    of_ext = '.sparse'
    if live:
        out_file = os.path.join(args.output, 'extracted-features' + of_ext)
    else:
        of_bn = os.path.join(args.output, os.path.basename(args.corpus))
        out_file = '{}.relations{}'.format(of_bn, of_ext)

    # dump
    dump_all(X_gen, y_gen, out_file, labtor.labelset_, docs,
             instance_generator)

    # dump vocabulary
    vocab_file = out_file + '.vocab'
    dump_vocabulary(vzer.vocabulary_, vocab_file)
