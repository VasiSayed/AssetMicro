

from .models import Asset, AssetPurchaseInfo, AssetWarrantyAMC, AssetMeasure, AssetAttachment
from rest_framework import serializers
from config.models import UserDatabase

class UserDatabaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserDatabase
        fields = '__all__'

class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = '__all__'

class AssetPurchaseInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetPurchaseInfo
        exclude = ('asset',)

class AssetWarrantyAMCSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetWarrantyAMC
        exclude = ('asset',)

class AssetMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetMeasure
        exclude = ('asset',)

class AssetAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetAttachment
        exclude = ('asset',)
