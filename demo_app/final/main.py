import webapp2
from google.appengine.api import users
from google.appengine.api import images
from google.appengine.api import taskqueue
from google.appengine.api.images import Image
from google.appengine.ext import blobstore
from google.appengine.ext import ndb
from google.appengine.ext.webapp import blobstore_handlers

import os
import jinja2

jinja_env = jinja2.Environment(
	loader=jinja2.FileSystemLoader(os.path.dirname(__file__) + '/templates'),
	extensions = ['jinja2.ext.autoescape']
)

def is_logged_in():
	return not users.get_current_user() is None

class Comment(ndb.Model):
	content = ndb.TextProperty()
	timestamp = ndb.DateTimeProperty(auto_now_add=True)
	author = ndb.UserProperty()

class Photo(ndb.Model):
	caption = ndb.StringProperty()
	timestamp = ndb.DateTimeProperty(auto_now_add=True)
	tags = ndb.StringProperty(repeated=True)
	owner = ndb.UserProperty()
	photo_blob_key = ndb.StringProperty()
	thumbnail = ndb.BlobProperty()
	thumbnailed = ndb.BooleanProperty(default=False)
	private = ndb.BooleanProperty()
	content_type = ndb.StringProperty()
	comments = ndb.StructuredProperty(Comment, repeated=True)

class PostUploadHandler(webapp2.RequestHandler):
	def get(self):
		template = jinja_env.get_template('post_upload.html')
		self.response.out.write(template.render({
			'current_user': None if not users.get_current_user() else users.get_current_user().nickname(),
			'login_url': users.create_login_url(self.request.uri),
			'logout_url': users.create_logout_url('/')
		}))

class PhotoUploadHandler(blobstore_handlers.BlobstoreUploadHandler):
	def post(self):
		photos = self.get_uploads('photo')
		photo_info = photos[0]

		caption = self.request.get('caption')
		tags = [tag.strip() for tag in self.request.get('tags').split(',')]
		private = self.request.get('private')

		new_photo = Photo(
			caption = caption,
			tags = tags,
			owner = users.get_current_user(),
			photo_blob_key = str(photo_info.key()),
			private = True if private == 'on' else False,
			content_type = photo_info.content_type,
			thumbnail = None
		)

		new_photo.put()

		self.redirect('/post_upload')

class PhotoDownloadHandler(blobstore_handlers.BlobstoreDownloadHandler):
	def get(self, key):
		blob_info = blobstore.BlobInfo.get(key)
		self.send_blob(blob_info)

class ThumbnailHandler(webapp2.RequestHandler):
	def get(self, key):
		photo = Photo.get_by_id(int(key))

		self.response.headers['Content-Type'] = str(photo.content_type)
		self.response.out.write(photo.thumbnail)

class NewPhotoHandler(webapp2.RequestHandler):
	def get(self):
		if not is_logged_in():
			self.redirect(users.create_login_url(self.request.uri))

		upload_url = blobstore.create_upload_url('/upload_photo')

		template = jinja_env.get_template('new_photo.html')
		self.response.out.write(template.render({
			'upload_url': upload_url,
			'current_user': users.get_current_user().nickname(),
			'logout_url': users.create_logout_url('/')
		}))

class PhotoDetailsHandler(webapp2.RequestHandler):
	def get(self, key):
		photo = Photo.get_by_id(int(key))

		template = jinja_env.get_template('photo_details.html');
		self.response.out.write(template.render({
			'photo': photo,
			'current_user': None if not users.get_current_user() else users.get_current_user().nickname(),
			'login_url': users.create_login_url(self.request.uri),
			'logout_url': users.create_logout_url('/')
		}))

class IndexHandler(webapp2.RequestHandler):
	def get(self):
		template_values = {'current_user': users.get_current_user()}
		if is_logged_in():
			q = Photo.query(Photo.owner == users.get_current_user())
			template_values['photos'] = q
			template_values['logout_url'] = users.create_logout_url('/')
		else:
			q = Photo.query(Photo.private == False)
			template_values['photos'] = q
			template_values['login_url'] = users.create_login_url(self.request.uri)

		template = jinja_env.get_template('index.html')
		self.response.out.write(template.render(template_values))

class UserHomeHandler(webapp2.RequestHandler):
	def get(self):
		if not is_logged_in():
			self.redirect('/')

		q = Photo.query(Photo.owner == users.get_current_user())

		template = jinja_env.get_template('user_home.html')
		self.response.out.write(template.render({
			'current_user': users.get_current_user().nickname(),
			'logout_url': users.create_logout_url('/'),
			'photos': q
		}))

class SearchHandler(webapp2.RequestHandler):
	def get(self, search_tag):
		if is_logged_in():
			q = Photo.query(ndb.AND(Photo.tags.IN([search_tag]), Photo.private == False))
			q2 = Photo.query(ndb.AND(Photo.tags.IN([search_tag]), Photo.owner == users.get_current_user()))
			photos = [photo for photo in q]
			for photo in q2:
				if not photo in photos:
					photos.append(photo)
		else:
			photos = Photo.query(ndb.AND(Photo.tags.IN([search_tag]), Photo.private == False))

		template = jinja_env.get_template('search_results.html')
		self.response.out.write(template.render({
			'photos': photos,
			'search_tag': search_tag,
			'current_user': None if not users.get_current_user() else users.get_current_user().nickname(),
			'login_url': users.create_login_url(self.request.uri),
			'logout_url': users.create_logout_url('/'),
		}))

class GenerateThumbnailHandler(webapp2.RequestHandler):
	def post(self):
		key = int(self.request.get('key'))

		photo = Photo.get_by_id(key)
		raw_image = Image(blob_key=photo.photo_blob_key)
		raw_image.resize(128, 128)
		thumbnail = raw_image.execute_transforms()

		photo.thumbnail = thumbnail
		photo.thumbnailed = True

		photo.put()

class CronThumbnailHandler(webapp2.RequestHandler):
	def get(self):
		q = Photo.query(Photo.thumbnailed == False)
		for photo in q:
			taskqueue.add(url='/generate_thumbnail', params = {'key': photo.key.id() }, method="POST")

class AllPhotosHandler(webapp2.RequestHandler):
	def get(self):
		if not is_logged_in():
			self.redirect(users.create_login_url(self.request.uri))

		q = Photo.query(ndb.OR(Photo.private == False, Photo.owner == users.get_current_user()))
		template = jinja_env.get_template('all_photos.html')
		self.response.out.write(template.render({
			'current_user': users.get_current_user().nickname(),
			'logout_url': users.create_logout_url('/'),
			'photos': q
		}))

class AddCommentHandler(webapp2.RequestHandler):
	def post(self):
		key = int(self.request.get('photo_key'))
		content = self.request.get('content')

		photo = Photo.get_by_id(key)
		comment = Comment(
			content = content,
			author = users.get_current_user()
		)

		photo.comments.append(comment)
		photo.put()

		self.redirect('/photo_details/%d' % (key))

routes = [
	('/add_comment', AddCommentHandler),
	('/all_photos', AllPhotosHandler),
	('/post_upload', PostUploadHandler),
	('/cron_thumbnail', CronThumbnailHandler),
	('/generate_thumbnail', GenerateThumbnailHandler),
	('/search/(.*)', SearchHandler),
	('/photo/([^/]+)', PhotoDownloadHandler),
	('/photo_details/(\d+)', PhotoDetailsHandler),
	('/thumbnail/(\d+)', ThumbnailHandler),
	('/upload_photo', PhotoUploadHandler),
	('/new_photo', NewPhotoHandler),
	('/user_home', UserHomeHandler), 
	('/.*', IndexHandler),
]

app = webapp2.WSGIApplication(routes, debug=True)