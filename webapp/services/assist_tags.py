from webapp.services.image_tags import (
    ImageTagMetadata as AssistTagMetadata,
    ImageTagService,
    parse_image_tag_filename as parse_assist_tag_filename,
)
from webapp.services.resources import ResourceService


class AssistTagService(ImageTagService):
    def __init__(self, resources: ResourceService) -> None:
        super().__init__(resources, directory="assist/assist_tags", kind="Assist tag")
