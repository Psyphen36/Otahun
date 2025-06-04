from tortoise.backends.base.config_generator import expand_db_url
from os import environ as env


tortoise = {
  "connections": {
    # "default": expand_db_url(postgres_database_url)
    # PostgreSQL Db URI
    "default": expand_db_url("DATABASE_URL")
    # "default": expand_db_url("sqlite://tempdb")
  },
  "apps": {
    "default": {
      "models": [
        "models"
      ]
    }
  }
}

del expand_db_url

tortoise["connections"]["default"]["credentials"]["ssl"] = "disable"



# # Jishaku Flags

# flags = [
#   "no underscore",
#   "hide",
#   "retain",
#   "force paginator",
#   "no dm_traceback",
# ]

# for flag in flags: env[("jishaku_"+flag).upper().replace(" ","_")] = "t"
# del flags

