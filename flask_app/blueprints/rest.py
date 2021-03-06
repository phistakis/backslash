# pylint: disable=no-member
import math
import os

import requests

from flask import Blueprint, abort, request, jsonify, current_app, Response
from flask_restful import Api, reqparse
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import func
from sqlalchemy.orm import aliased

from flask_simple_api import error_abort
from flask_security import current_user
from .. import models
from ..models import Error, Session, Test, User, Subject, db
from .. import activity
from ..utils.identification import parse_test_id, parse_session_id
from ..utils.rest import ModelResource
from ..filters import filter_by_statuses
from ..search import get_orm_query_from_search_string

blueprint = Blueprint('rest', __name__, url_prefix='/rest')


rest = Api(blueprint)


def _resource(*args, **kwargs):
    def decorator(resource):
        rest.add_resource(resource, *args, **kwargs)
        return resource
    return decorator

##########################################################################

session_parser = reqparse.RequestParser()
session_parser.add_argument('user_id', type=int, default=None)
session_parser.add_argument('subject_name', type=str, default=None)
session_parser.add_argument('search', type=str, default=None)
session_parser.add_argument('parent_logical_id', type=str, default=None)
session_parser.add_argument('id', type=str, default=None)

@_resource('/sessions', '/sessions/<object_id>')
class SessionResource(ModelResource):

    MODEL = Session
    DEFAULT_SORT = (Session.start_time.desc(),)

    def _get_object_by_id(self, object_id):
        return _get_object_by_id_or_logical_id(self.MODEL, object_id)

    def _get_iterator(self):
        args = session_parser.parse_args()

        if args.id is not None:
            return _get_query_by_id_or_logical_id(self.MODEL, args.id)
        if args.search:
            returned = get_orm_query_from_search_string('session', args.search, abort_on_syntax_error=True)
        else:
            returned = super(SessionResource, self)._get_iterator()

        if args.parent_logical_id is not None:
            returned =  returned.filter(Session.parent_logical_id == args.parent_logical_id)
        else:
            returned = returned.filter(Session.parent_logical_id == None)
        if args.subject_name is not None:
            returned = (
                returned
                .join(Session.subject_instances)
                .join(Subject)
                .filter(Subject.name == args.subject_name))

        if args.user_id is not None:
            returned = returned.filter(Session.user_id == args.user_id)

        returned = filter_by_statuses(returned, self.MODEL)

        return returned


test_query_parser = reqparse.RequestParser()
test_query_parser.add_argument('session_id', default=None)
test_query_parser.add_argument('info_id', type=int, default=None)
test_query_parser.add_argument('search', type=str, default=None)
test_query_parser.add_argument('after_index', type=int, default=None)
test_query_parser.add_argument('before_index', type=int, default=None)


@_resource('/tests', '/tests/<object_id>', '/sessions/<session_id>/tests')
class TestResource(ModelResource):

    MODEL = Test
    DEFAULT_SORT = (Test.start_time.desc(),)
    from .filter_configs import TEST_FILTERS as FILTER_CONFIG

    def _get_object_by_id(self, object_id):
        return _get_object_by_id_or_logical_id(self.MODEL, object_id)

    def _get_iterator(self):
        args = test_query_parser.parse_args()

        if args.session_id is None:
            args.session_id = request.view_args.get('session_id')

        if args.search:
            returned = get_orm_query_from_search_string('test', args.search, abort_on_syntax_error=True)
        else:
            returned = super(TestResource, self)._get_iterator()


        #get session
        if args.session_id is not None:
            using_logical_id = False
            try:
                session_id = int(args.session_id)
                stmt = db.session.query(Session).filter(Session.id == session_id).subquery()
                children = db.session.query(Session.id).filter(Session.parent_logical_id == stmt.c.logical_id).all()
            except ValueError:
                using_logical_id = True
                children = db.session.query(Session.id).filter(Session.parent_logical_id == args.session_id).all()

            returned = Test.query.join(Session).filter(Session.logical_id == args.session_id) if using_logical_id else \
                        returned.filter(Test.session_id == session_id)
            if children:
                children_ids = [child[0] for child in children]
                returned = returned.union(Test.query.filter(Test.session_id.in_(children_ids)))


        if args.info_id is not None:
            returned = returned.filter(Test.test_info_id == args.info_id)

        returned = filter_by_statuses(returned, Test)

        if args.session_id is not None:
            if args.after_index is not None:
                returned = returned.filter(self.MODEL.test_index > args.after_index).order_by(self.MODEL.test_index.asc()).limit(1).all()
            elif args.before_index is not None:
                returned = returned.filter(self.MODEL.test_index < args.before_index).order_by(self.MODEL.test_index.desc()).limit(1).all()

        return returned

    def _paginate(self, query, metadata):
        count_pages = bool(request.args.get('session_id'))
        if count_pages:
            num_objects = query.count()
        else:
            num_objects = None
        returned = super()._paginate(query, metadata)
        if count_pages:
            metadata['num_pages'] = math.ceil(num_objects / metadata['page_size']) or 1
        return returned


@_resource('/test_infos/<object_id>')
class TestInfoResource(ModelResource):

    MODEL = models.TestInformation


@_resource('/subjects', '/subjects/<object_id>')
class SubjectResource(ModelResource):

    MODEL = models.Subject
    ONLY_FIELDS = ['id', 'name', 'last_activity']
    SORTABLE_FIELDS = ['last_activity', 'name']
    INVERSE_SORTS = ['last_activity']

    def _get_object_by_id(self, object_id):
        try:
            object_id = int(object_id)
        except ValueError:
            try:
                return self.MODEL.query.filter(models.Subject.name == object_id).one()
            except NoResultFound:
                abort(requests.codes.not_found)
        else:
            return self.MODEL.query.get_or_404(object_id)


def _get_query_by_id_or_logical_id(model, object_id):
    query_filter = model.logical_id == object_id
    try:
        numeric_object_id = int(object_id)
    except ValueError:
        pass
    else:
        query_filter = (model.id == numeric_object_id) | query_filter
    return model.query.filter(query_filter)

def _get_object_by_id_or_logical_id(model, object_id):
    returned = _get_query_by_id_or_logical_id(model, object_id).first()
    if returned is None:
        abort(requests.codes.not_found) # pylint: disable=no-member
    return returned


session_test_user_query_parser = reqparse.RequestParser()
session_test_user_query_parser.add_argument('session_id', type=int, default=None)
session_test_user_query_parser.add_argument('test_id', type=int, default=None)
session_test_user_query_parser.add_argument('user_id', type=int, default=None)

session_test_query_parser = reqparse.RequestParser()
session_test_query_parser.add_argument('session_id', type=int, default=None)
session_test_query_parser.add_argument('test_id', type=int, default=None)

errors_query_parser = reqparse.RequestParser()
errors_query_parser.add_argument('session_id', default=None)
errors_query_parser.add_argument('test_id', default=None)


@_resource('/warnings', '/warnings/<int:object_id>')
class WarningsResource(ModelResource):

    MODEL = models.Warning
    DEFAULT_SORT = (models.Warning.timestamp.asc(),)

    def _get_iterator(self):
        args = session_test_user_query_parser.parse_args()
        returned = self.MODEL.query.filter_by(test_id=args.test_id, session_id=args.session_id)
        return returned


@_resource('/errors', '/errors/<int:object_id>')
class ErrorResource(ModelResource):

    MODEL = Error
    DEFAULT_SORT = (Error.timestamp.asc(),)

    def _get_iterator(self):
        args = errors_query_parser.parse_args()

        if args.session_id is not None:
            return Error.query.filter_by(session_id=parse_session_id(args.session_id))
        elif args.test_id is not None:
            return Error.query.filter_by(test_id=parse_test_id(args.test_id))
        abort(requests.codes.bad_request)


@blueprint.route('/tracebacks/<uuid>')
def get_traceback(uuid):
    if not current_app.config['DEBUG'] and not current_app.config['TESTING']:
        abort(requests.codes.not_found)
    path = _get_traceback_path(uuid)
    if not os.path.isfile(path):
        abort(requests.codes.not_found)
    def sender():
        with open(path, 'rb') as f:
            while True:
                buff = f.read(4096)
                if not buff:
                    break
                yield buff
    return Response(sender(), headers={'Content-Encoding': 'gzip', 'Content-Type': 'application/json'})


def _get_traceback_path(uuid):
    return os.path.join(current_app.config['TRACEBACK_DIR'], uuid[:2], uuid + '.gz')


@_resource('/users', '/users/<object_id>')
class UserResource(ModelResource):

    ONLY_FIELDS = ['id', 'email', 'last_activity']
    SORTABLE_FIELDS = ['last_activity', 'email', 'first_name', 'last_name']
    INVERSE_SORTS = ['last_activity']
    MODEL = User

    def _get_iterator(self):
        returned = super()._get_iterator()
        if request.args.get('current_user'):
            if not current_user.is_authenticated:
                return []
            object_id = current_user.id
            returned = returned.filter(self.MODEL.id == object_id)

        filter = request.args.get('filter')
        if filter:
            filter = filter.lower()
            returned = returned.filter(func.lower(User.first_name).contains(filter) | func.lower(User.last_name).contains(filter) | func.lower(User.email).contains(filter))
        return returned

    def _get_object_by_id(self, object_id):
        try:
            object_id = int(object_id)
        except ValueError:
            try:
                object_id = User.query.filter_by(email=object_id).one().id
            except NoResultFound:
                abort(requests.codes.not_found)
        return User.query.get_or_404(int(object_id))

@_resource('/comments', '/comments/<object_id>', methods=['get', 'delete', 'put'])
class CommentResource(ModelResource):

    MODEL = models.Comment
    DEFAULT_SORT = (models.Comment.timestamp.asc(),)

    def _get_iterator(self):
        args = session_test_query_parser.parse_args()
        if not ((args.session_id is not None) ^ (args.test_id is not None)): # pylint: disable=superfluous-parens
            error_abort('Either test_id or session_id must be passed to the query')

        return models.Comment.query.filter_by(session_id=args.session_id, test_id=args.test_id)

    def delete(self, object_id=None):
        if object_id is None:
            error_abort('Not implemented', code=requests.codes.not_implemented)
        comment = models.Comment.query.get_or_404(object_id)
        if comment.session_id is not None:
            obj = models.Session.query.get(comment.session_id)
        else:
            obj = models.Test.query.get(comment.test_id)
        if comment.user_id != current_user.id:
            error_abort('Not allowed to delete comment', code=requests.codes.forbidden)
        obj.num_comments = type(obj).num_comments - 1
        models.db.session.add(obj)
        models.db.session.delete(comment)
        models.db.session.commit()

    def put(self, object_id=None):
        if object_id is None:
            error_abort('Not implemented', code=requests.codes.not_implemented)
        comment = models.Comment.query.get_or_404(object_id)
        if comment.user_id != current_user.id:
            error_abort('Not allowed to delete comment', code=requests.codes.forbidden)
        comment.comment = request.get_json().get('comment', {}).get('comment')
        comment.edited = True
        models.db.session.add(comment)
        models.db.session.commit()
        return jsonify({'comment': self._render_single(comment, in_collection=False)})


related_entity_parser = reqparse.RequestParser()
related_entity_parser.add_argument('session_id', default=None, type=int)
related_entity_parser.add_argument('test_id', default=None, type=int)


@_resource('/entities', '/entities/<int:object_id>')
class RelatedEntityResource(ModelResource):

    MODEL = models.Entity

    def _get_iterator(self):
        args = related_entity_parser.parse_args()

        if not ((args.session_id is None) ^ (args.test_id is None)):
            error_abort('Either test_id or session_id must be provided')

        if args.session_id is not None:
            return models.Entity.query.join(models.session_entity).filter(models.session_entity.c.session_id == args.session_id)
        elif args.test_id is not None:
            return models.Entity.query.join(models.test_entity).filter(models.test_entity.c.test_id == args.test_id)
        else:
            raise NotImplementedError() # pragma: no cover


@_resource('/migrations', '/migrations/<object_id>')
class MigrationsResource(ModelResource):

    MODEL = models.BackgroundMigration
    DEFAULT_SORT = (models.BackgroundMigration.started_time.desc(),)
    ONLY_FIELDS = [
        'id',
        'name',
        'started',
        'started_time',
        'finished',
        'finished_time',
        'total_num_objects',
        'remaining_num_objects'
    ]


@_resource('/cases', '/cases/<object_id>')
class CaseResource(ModelResource):

    MODEL = models.TestInformation
    DEFAULT_SORT = (models.TestInformation.name, models.TestInformation.file_name, models.TestInformation.class_name)

    def _get_iterator(self):
        search = request.args.get('search')
        if search:
            returned = get_orm_query_from_search_string('case', search, abort_on_syntax_error=True)
        else:
            returned = super()._get_iterator()
        returned = returned.filter(~self.MODEL.file_name.like('/%'))
        return returned
