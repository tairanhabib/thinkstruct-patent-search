"""Patent passage search."""
import logging

# The model libraries print two notices on every start. Neither is an error and neither is something
# a user of this tool can act on, so they are dropped. Everything else those libraries log still shows.
_NOTICES = ("Redirects are currently not supported",  # PyTorch: a feature macOS does not have, unused here
            "unauthenticated requests to the HF Hub")  # Hugging Face: no account token set; none is needed


class _DropNotices(logging.Filter):
    def filter(self, record):
        return not any(notice in str(record.msg) for notice in _NOTICES)


for _name in ("torch.distributed.elastic.multiprocessing.redirects", "huggingface_hub.utils._http"):
    logging.getLogger(_name).addFilter(_DropNotices())
