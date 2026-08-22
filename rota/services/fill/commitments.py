from rota.models import RecurringCommitment
from rota.services import entries


def run(ctx, actor, result):
    commitments = (RecurringCommitment.objects
                   .filter(clinician__active=True)
                   .select_related("clinician", "session_type", "site"))
    for com in commitments:
        for day in ctx.open_days:
            if not com.occurs_on(day):
                continue
            for part in com.parts_list():
                cid = com.clinician_id
                if not (ctx.works_on(cid, day, part)
                        and ctx.is_free(cid, day, part)):
                    continue
                entry = entries.assign(
                    actor, com.clinician, day, part, com.session_type,
                    site=com.site or com.session_type.default_site,
                    manually_set=False, fill_reason="commitment",
                )
                ctx.record(entry)
                result.created += 1
