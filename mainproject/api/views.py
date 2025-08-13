import socket
import logging
from io import StringIO

from django.db import transaction, connections
from django.core.management import call_command
from django.conf import settings

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser

from .models import Asset, AssetPurchaseInfo, AssetWarrantyAMC, AssetMeasure, AssetAttachment
from .serializers import (
    AssetSerializer, AssetPurchaseInfoSerializer, AssetWarrantyAMCSerializer,
    AssetMeasureSerializer, AssetAttachmentSerializer
)
from .utils import decrypt_password, test_db_connection, add_db_alias,ensure_alias_for_client

logger = logging.getLogger("asset.registerdb")

# class RegisterDBAPIView(APIView):
#     authentication_classes = []
#     permission_classes = []
#     parser_classes = [JSONParser, MultiPartParser, FormParser]

#     def post(self, request):
#         logger.info("RegisterDBAPIView called")
#         logger.debug("Incoming payload keys: %s", list(request.data.keys()))

#         ser = UserDatabaseSerializer(data=request.data)
#         if not ser.is_valid():
#             logger.warning("Serializer invalid: %s", ser.errors)
#             return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

#         d = ser.validated_data
#         user_id = d['user_id']
#         username = d.get('username')
#         db_alias = f"client_{user_id}"

#         logger.info("Validated for user_id=%s, username=%s, alias=%s",
#                     user_id, username, db_alias)
#         logger.debug("DB target: %s@%s:%s/%s (type=%s)",
#                      d['db_user'], d['db_host'], d['db_port'], d['db_name'], d.get('db_type'))

#         # Already registered?
#         if UserDatabase.objects.filter(user_id=user_id).exists():
#             logger.warning("DB entry already exists for user_id=%s", user_id)
#             return Response(
#                 {'detail': f"DB entry already exists for user_id {user_id}."},
#                 status=status.HTTP_400_BAD_REQUEST
#             )

#         # Host resolvable?
#         try:
#             ip = socket.gethostbyname(d['db_host'])
#             logger.debug("Resolved host %s -> %s", d['db_host'], ip)
#         except socket.error:
#             logger.error("Host not resolvable: %s", d['db_host'])
#             return Response({'detail': f"Host '{d['db_host']}' is not resolvable."},
#                             status=status.HTTP_400_BAD_REQUEST)

#         # Decrypt password
#         try:
#             real_pw = decrypt_password(d['db_password'])
#         except Exception as e:
#             logger.exception("Password decryption failed")
#             return Response({'detail': f"Failed to decrypt password: {str(e)}"},
#                             status=status.HTTP_400_BAD_REQUEST)

#         # Live connection test
#         ok, err = test_db_connection(
#             name=d['db_name'], user=d['db_user'], password=real_pw, host=d['db_host'], port=d['db_port']
#         )
#         if not ok:
#             logger.error("Connection test failed: %s", err)
#             return Response({'detail': f'Connect failed: {err}'}, status=status.HTTP_400_BAD_REQUEST)

#         if db_alias in settings.DATABASES:
#             logger.warning("DB alias already in settings: %s", db_alias)
#             return Response({'detail': f"DB alias '{db_alias}' already exists in settings."},
#                             status=status.HTTP_400_BAD_REQUEST)

#         entry = UserDatabase.objects.create(
#             user_id=user_id,
#             username=username,
#             db_name=d['db_name'],
#             db_user=d['db_user'],
#             db_password=d['db_password'],  # encrypted
#             db_host=d['db_host'],
#             db_port=d['db_port'],
#             db_type=d.get('db_type') or 'self_hosted'
#         )
#         logger.info("UserDatabase row created id=%s", entry.id)

#         try:
#             # Register runtime DB alias
#             add_db_alias(
#                 alias=db_alias,
#                 db_name=d['db_name'],
#                 db_user=d['db_user'],
#                 db_password=real_pw,
#                 db_host=d['db_host'],
#                 db_port=d['db_port'],
#             )

#             logger.info("Running migrations for app='api' on database='%s'", db_alias)
#             out = StringIO()
#             call_command('migrate', 'api', database=db_alias, interactive=False, verbosity=1, stdout=out)
#             logger.info("Migrate output:\n%s", out.getvalue())

#             try:
#                 out2 = StringIO()
#                 call_command('showmigrations', 'api', database=db_alias, stdout=out2, verbosity=1)
#                 logger.debug("Showmigrations:\n%s", out2.getvalue())
#             except Exception:
#                 logger.debug("showmigrations failed (non-fatal)", exc_info=True)

#         except Exception as e:
#             logger.exception("Migration or alias setup failed for alias=%s", db_alias)
#             # cleanup
#             entry.delete()
#             settings.DATABASES.pop(db_alias, None)
#             try:
#                 connections.databases.pop(db_alias, None)
#             except Exception:
#                 pass
#             return Response({'detail': f"Migration failed: {str(e)}"},
#                             status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#         finally:
#             try:
#                 connections[db_alias].close()
#                 logger.debug("Closed connection for alias %s", db_alias)
#             except Exception:
#                 logger.debug("No connection to close for alias %s", db_alias)

#         logger.info("DB registered and API tables migrated for alias=%s", db_alias)
#         return Response(
#             {'detail': 'DB registered and API tables migrated.', 'alias': db_alias},
#             status=status.HTTP_201_CREATED
#         )


class RegisterDBByClientAPIView(APIView):
    """
    POST /api/register-db/
    {
      "client_id": 1845
      # or
      "client_username": "Loadha"
    }
    """
    authentication_classes = []  
    permission_classes = []
    parser_classes = [JSONParser]

    def post(self, request):
        client_id = (request.data or {}).get("client_id")
        client_username = (request.data or {}).get("client_username")

        if not client_id and not client_username:
            return Response({"detail": "Provide client_id or client_username."}, status=400)

        try:
            alias = ensure_alias_for_client(client_id=client_id, client_username=client_username)


            if settings.DEBUG or str(os.getenv("ASSET_AUTO_MIGRATE", "0")) == "1":
                out = StringIO()
                call_command("migrate", "api", database=alias, interactive=False, verbosity=1, stdout=out)
                logger.info("Migrated app 'api' on %s\n%s", alias, out.getvalue())

            try:
                connections[alias].close()
            except Exception:
                pass

            return Response({"detail": "Alias ready", "alias": alias}, status=201)

        except Exception as e:
            logger.exception("RegisterDBByClient failed")
            return Response({"detail": str(e)}, status=400)


# sample post payload{
#   "user_id": 12,
#   "username": "AcmeCorp",
#   "db_name": "acmecorp_db",
#   "db_user": "acmecorp",
#   "db_password": "<FERNET_ENCRYPTED_STRING>",
#   "db_host": "localhost",
#   "db_port": "5432",
#   "db_type": "self_hosted"
# }




class AssetBundleCreateAPIView(APIView):
    """
    Accepts a single payload with:
    {
      "Asset": {...},
      "AssetPurchaseInfo": {...},              # optional
      "AssetWarrantyAMC": {...},               # optional
      "AssetMeasure": [{...}, {...}],          # optional list
      "AssetAttachment": [{...}, {...}]        # optional list
    }
    Creates all rows in a single DB transaction; rolls back on any error.
    """
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request):
        data = request.data

        asset_data = data.get('Asset')
        if not asset_data:
            return Response({'detail': "Missing 'Asset' object."}, status=status.HTTP_400_BAD_REQUEST)

        purchase_data = data.get('AssetPurchaseInfo')
        warranty_data = data.get('AssetWarrantyAMC')
        measures_data = data.get('AssetMeasure', [])
        attach_data = data.get('AssetAttachment', [])

        if measures_data and not isinstance(measures_data, list):
            return Response({'detail': "'AssetMeasure' must be a list."}, status=status.HTTP_400_BAD_REQUEST)
        if attach_data and not isinstance(attach_data, list):
            return Response({'detail': "'AssetAttachment' must be a list."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                asset_ser = AssetSerializer(data=asset_data)
                asset_ser.is_valid(raise_exception=True)
                asset = asset_ser.save()

                if purchase_data:
                    pi_ser = AssetPurchaseInfoSerializer(data=purchase_data)
                    pi_ser.is_valid(raise_exception=True)
                    AssetPurchaseInfo.objects.create(asset=asset, **pi_ser.validated_data)

                if warranty_data:
                    wa_ser = AssetWarrantyAMCSerializer(data=warranty_data)
                    wa_ser.is_valid(raise_exception=True)
                    AssetWarrantyAMC.objects.create(asset=asset, **wa_ser.validated_data)

                created_measures = []
                for m in measures_data:
                    m_ser = AssetMeasureSerializer(data=m)
                    m_ser.is_valid(raise_exception=True)
                    created_measures.append(AssetMeasure(asset=asset, **m_ser.validated_data))
                if created_measures:
                    AssetMeasure.objects.bulk_create(created_measures)


                created_attachments = []
                for a in attach_data:
                    a_ser = AssetAttachmentSerializer(data=a)
                    a_ser.is_valid(raise_exception=True)
                    created_attachments.append(AssetAttachment(asset=asset, **a_ser.validated_data))
                if created_attachments:
                    AssetAttachment.objects.bulk_create(created_attachments)

                return Response(
                    {
                        'detail': 'Asset bundle created successfully.',
                        'asset_id': asset.id,
                    },
                    status=status.HTTP_201_CREATED
                )

        except Exception as e:
            return Response({'detail': f'Creation failed: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)


    