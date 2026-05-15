from rest_framework import serializers


class OpsHealthSnapshotSerializer(serializers.Serializer):
    schema_version = serializers.CharField()
    generated_at = serializers.DateTimeField()
    system = serializers.DictField()
    processes = serializers.DictField()
    disk = serializers.DictField()
    network = serializers.DictField()
    services = serializers.DictField()
    application = serializers.DictField()
    postgres_detail = serializers.DictField(required=False)
    application_surfaces = serializers.DictField(required=False)
    livewire_detail = serializers.DictField(required=False)


class OpsSummarySerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    overall_status = serializers.CharField()
    headline = serializers.CharField()
    highlights = serializers.ListField(child=serializers.CharField())
    tiles = serializers.ListField(child=serializers.DictField())


class OpsTilesSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    tiles = serializers.ListField(child=serializers.DictField())
