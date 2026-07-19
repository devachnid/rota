from rota.models import ClosedDay, PracticeSettings


def is_open(day):
    settings = PracticeSettings.load()
    if day.weekday() not in settings.open_weekday_list():
        return False
    return not ClosedDay.objects.filter(day=day).exists()
