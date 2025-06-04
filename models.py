from tortoise import fields
from tortoise.models import Model

class DBChannel(Model):
  id = fields.BigIntField(pk=True)
  active = fields.BooleanField(default=lambda:False)

  def toggle_active(self):
    self.active=not self.active
    return self.save()

class DBUser(Model):
  id = fields.BigIntField(pk=True)
  sid = fields.CharField(unique=True, max_length=50)
  auth_token = fields.TextField(null=True)
  
  def set_token(self, token: str):
    self.auth_token = token
    return self.save()
