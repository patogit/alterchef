# -*- coding: utf-8 -*-
from os import path
import shutil
import StringIO
import tempfile
import subprocess

from test.test_support import EnvironmentVarGuard
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse

from models import IncludePackages, IncludeFiles, FwJob, FwProfile, Network
from forms import IncludePackagesForm

TEST_DATA_PATH = path.join(path.dirname(__file__), "test_data")
PROFILES_PATH = path.abspath(path.join(TEST_DATA_PATH, "profiles"))
TEST_PROFILE_PATH = path.join(PROFILES_PATH, "test.org.ar")


class ViewsTest(TestCase):
    def test_index(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)


class IncludePackagesTest(TestCase):
    def test_read_from_disk(self):
        ip = IncludePackages.load(open(path.join(TEST_PROFILE_PATH, "include_packages")))
        self.assertEqual(ip.include, ["kmod-batman-adv", "kmod-ipv6", "dnsmasq-dhcpv6",
                                      "ip6tables", "kmod-ath9k-htc", "safe-reboot", "iperf"])
        self.assertEqual(ip.exclude, ["dnsmasq", "qos-scripts"])

    def test_write_to_disk(self):
        ip = IncludePackages(include=["iperf", "safe-reboot"],
                             exclude=["dnsmasq", "qos-scripts"])
        output = StringIO.StringIO()
        ip.dump(output)
        self.assertEqual(output.getvalue(), "iperf\nsafe-reboot\n-dnsmasq\n-qos-scripts")

    def test_form(self):
        ip = IncludePackages(include=["iperf", "safe-reboot"],
                             exclude=["dnsmasq", "qos-scripts"])
        form = IncludePackagesForm.from_instance(ip)
        self.assertTrue(form.is_valid())

    def test_string(self):
        ip = IncludePackages.from_str("")
        self.assertEqual(ip.to_str(), "")


class IncludeFilesTest(TestCase):

    def read_file(self, filename):
        return open(path.join(TEST_PROFILE_PATH, "include_files", filename)).read()

    def read_test_files(self):
        files = {}
        for filename in ["/etc/profile", "/etc/config/batman-adv", "/etc/config/batmesh",
                         "/etc/uci-defaults/add-opkg-repo-altermundi",
                         "/etc/uci-defaults/set-timezone-art3"]:
            files[filename] = self.read_file(filename[1:])
        return files

    def test_read_from_disk(self):
        inc_files = IncludeFiles.load(path.join(TEST_PROFILE_PATH, "include_files"))

        self.assertEqual(inc_files.files, self.read_test_files())

    def test_write_to_disk(self):
        inc_files = IncludeFiles(files=self.read_test_files())
        dest_dir = tempfile.mkdtemp()
        inc_files.dump(dest_dir)
        diff = subprocess.check_output(["diff", "-r", dest_dir, path.join(TEST_PROFILE_PATH, "include_files")], stderr=subprocess.STDOUT)
        self.assertEqual(diff, "")
        shutil.rmtree(dest_dir)  # cleaning up

    def test_load_from_tar(self):

        def generate_inmemory_tar(content):
            import StringIO
            import tarfile
            tar_sio = StringIO.StringIO()
            with tarfile.TarFile(fileobj=tar_sio, mode="w") as tar:
                content_sio = StringIO.StringIO()
                content_sio.write(content)
                content_sio.seek(0)
                info = tarfile.TarInfo(name=u"fóø".encode("utf-8"))
                info.size = len(content_sio.buf)
                tar.addfile(tarinfo=info, fileobj=content_sio)
            tar_sio.seek(0)
            tar_sio.name = "foo"
            return tar_sio

        content = u"testing únicódè"
        inc_files = IncludeFiles.load_from_tar(generate_inmemory_tar(content.encode("utf-8")))
        self.assertEqual(inc_files.files.values()[0], content)

        # if encoding is not utf-8 then we cant load the file
        self.assertRaises(UnicodeDecodeError, IncludeFiles.load_from_tar,
                          generate_inmemory_tar(content.encode("latin-1")))


class NetworkTest(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user("owner", "e@a.com", "password")
        self.admin = User.objects.create_user("admin", "e@a.com", "password")
        self.other_user = User.objects.create_user("other", "e@a.com", "password")

        self.network = Network.objects.create(name="quintanalibre.org.ar", user=self.owner,
                                              description="desc")
        self.network.admins.add(self.admin)
        self.network_edit_url = reverse('network-edit', kwargs={"slug": self.network.slug})

    def test_create_network_anonymous(self):
        response = self.client.get(reverse('network-create'))
        self.assertEqual(response.status_code, 302)

    def test_edit_owner(self):
        self.client.login(username="owner", password="password")
        response = self.client.get(self.network_edit_url)
        self.assertEqual(response.status_code, 200)
        self.client.post(self.network_edit_url, {"name": "owner.org.ar", "description": "desc"})
        self.assertEqual(Network.objects.get(pk=self.network.pk).name, "owner.org.ar")

    def test_edit_admin(self):
        self.client.login(username="admin", password="password")
        response = self.client.post(self.network_edit_url, {"name": "admin.org.ar", "description": "desc"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Network.objects.get(pk=self.network.pk).name, "admin.org.ar")

    def test_edit_other(self):
        self.client.login(username="other", password="password")
        response = self.client.post(self.network_edit_url, {"name": "other.org.ar", "description": "desc"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Network.objects.get(pk=self.network.pk).name, "quintanalibre.org.ar")


class FwProfileTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ninja", "e@a.com", "password")
        self.network = Network.objects.create(name="quintanalibre.org.ar", user=self.user)
        self.client.login(username="ninja", password="password")
        self.data = {
            "network": self.network.pk,
            "name": "node",
            "description": "foo",
            "openwrt_revision": "stable",
            "devices": [u"TLMR3220", u"UBNT"]
        }

    def assertLoginRequired(self, url):
        self.client.logout()
        response = self.client.get(url)
        self.assertRedirects(response, reverse('auth_login') + "?next=" + url,
                             status_code=302, target_status_code=200)

    def test_login_required(self):
        self.assertLoginRequired(reverse("fwprofile-create-simple"))
        self.client.login(username="ninja", password="password")

    def test_simple_creation(self):
        response = self.client.get(reverse("fwprofile-create-simple"))
        self.assertContains(response, "Create Firmware Profile")
        response = self.client.post(reverse("fwprofile-create-simple"),
                                    self.data, follow=True)
        self.assertContains(response, "Profile Detail")

        profile = FwProfile.objects.all()[0]
        self.assertItemsEqual(profile.devices, u"TLMR3220 UBNT")

    def test_simple_creation_with_based_on(self):
        response = self.client.post(reverse("fwprofile-create-simple"), self.data, follow=True)
        self.assertContains(response, "Profile Detail")
        data = self.data.copy()
        data.update({"name": "name2", "based_on": 1})
        response = self.client.post(reverse("fwprofile-create-simple"), data, follow=True)
        self.assertContains(response, "Profile Detail")

    def test_include_files_formset_files(self):
        from forms import IncludeFilesFormset
        form_data = {'form-TOTAL_FORMS': 1, 'form-INITIAL_FORMS': 0,
                     'form-0-path': u'/foo/bar', 'form-0-content': u'this is foo'}
        formset = IncludeFilesFormset(form_data)
        assert formset.is_valid() is True
        self.assertEqual(formset.include_files(), {u"/foo/bar": u'this is foo'})

    def test_edit(self):
        response = self.client.post(reverse("fwprofile-create-simple"), self.data, follow=True)
        url = reverse("fwprofile-edit-advanced", kwargs={"slug": FwProfile.objects.all()[0].slug})
        response = self.client.get(url)
        data = self.data.copy()
        data.update({'include-files-INITIAL_FORMS': u'0', 'include-files-MAX_NUM_FORMS': u'',
                    'include-files-TOTAL_FORMS': u'0', 'description': 'new_description'})
        response = self.client.post(url, data)
        self.assertEqual(FwProfile.objects.all()[0].description, 'new_description')

    def test_delete(self):
        response = self.client.post(reverse("fwprofile-create-simple"), self.data, follow=True)
        response = self.client.get(reverse("fwprofile-delete", kwargs={"slug": FwProfile.objects.all()[0].slug}))
        self.assertEqual(response.status_code, 200)

    def test_network_in_url_empty(self):
        response = self.client.get(reverse("fwprofile-create-advanced") + "?network=")
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("fwprofile-create-simple") + "?network=")
        self.assertEqual(response.status_code, 200)

    def test_network_in_url(self):
        response = self.client.get(reverse("fwprofile-create-advanced") + "?network=1")
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("fwprofile-create-simple") + "?network=1")
        self.assertEqual(response.status_code, 200)

    def test_simple_creation_without_network(self):
        self.data["network"] = ""
        response = self.client.post(reverse("fwprofile-create-simple") + "?network=", self.data, follow=True)
        self.assertEqual(response.status_code, 200)


class JobsTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("ninja", "e@a.com", "password")
        self.network = Network.objects.create(name="quintanalibre.org.ar", user=self.user)
        self.profile = FwProfile.objects.create(network=self.network)
        self.client.login(username="ninja", password="password")
        self.cook_url = reverse('cook', kwargs={'slug': self.profile.slug})
        self.job_data = {"devices": ["TLMR3220"], "revision": "stable"}
        self.env = EnvironmentVarGuard()
        self.env.set('LANG', '')

    def tearDown(self):
        FwJob.set_make_commands_func(FwJob.default_make_commands)

    def test_process_some_jobs(self):
        FwJob.objects.create(profile=self.profile, user=self.user, job_data=self.job_data)
        FwJob.objects.create(profile=self.profile, user=self.user, job_data=self.job_data)

        FwJob.set_make_commands_func(lambda *x: ["sleep 0.1"])

        self.assertEqual(len(FwJob.started.all()), 0)
        self.assertEqual(len(FwJob.waiting.all()), 2)

        FwJob.process_jobs(sync=True)
        self.assertEqual(len(FwJob.waiting.all()), 1)
        self.assertEqual(len(FwJob.finished.all()), 1)

        FwJob.process_jobs(sync=True)
        self.assertEqual(len(FwJob.finished.all()), 2)

    def test_failed_job(self):
        fwjob = FwJob.objects.create(profile=self.profile, user=self.user, job_data=self.job_data)
        FwJob.set_make_commands_func(lambda *x: ["ls /inexistent"])

        FwJob.process_jobs(sync=True)
        self.assertEqual(len(FwJob.failed.all()), 1)
        with self.env:
            fwjob = FwJob.objects.get(pk=fwjob.pk)
            self.assertTrue("No such file or directory" in fwjob.build_log)

    def _test_cook(self):
        response = self.client.get(self.cook_url)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(self.cook_url, {"other_devices": "TLMR3020", "openwrt_revision": "stable"})
        self.assertEqual(response.status_code, 302)

        self.assertEqual(len(FwJob.started.all()), 0)
        self.assertEqual(len(FwJob.waiting.all()), 1)
        FwJob.process_jobs()
        self.assertEqual(len(FwJob.started.all()), 1)
        self.assertEqual(len(FwJob.waiting.all()), 0)

    def test_make_commands(self):
        commands = FwJob.make_commands("quintanalibre.org.ar", "profile1", ["TLMR3220", "NONEatherosDefault"], "33333")
        self.assertTrue("33333 ar71xx quintanalibre.org.ar profile1 TLMR3220" in commands[0])
        self.assertTrue("33333 atheros quintanalibre.org.ar profile1 Default" in commands[1])

    def test_view_jobs(self):
        self.assertContains(self.client.get(reverse("view-jobs")), "List Jobs")

    def test_job_detail(self):
        fwjob = FwJob.objects.create(profile=self.profile, user=self.user, job_data=self.job_data)
        self.assertContains(self.client.get(reverse("fwjob-detail", kwargs={"pk": fwjob.pk})), "WAITING")
        fwjob.status = "FAILED"
        fwjob.build_log = "the log"
        fwjob.save()
        self.assertContains(self.client.get(reverse("fwjob-detail", kwargs={"pk": fwjob.pk})), "the log")


class DiffTests(TestCase):

    def test_diff_view(self):
        user = User.objects.create_user("ninja", "e@a.com", "password")
        network = Network.objects.create(name="quintanalibre.org.ar", user=user)
        profile1 = FwProfile.objects.create(network=network, name="p1", include_packages="pkg_two\npkg_three\n",
                                            include_files={"/foo": "foo\nfoo\n", "/bar": "bar\nbar\n"})
        profile2 = FwProfile.objects.create(network=network, name="p2", include_packages="pkg_one\npkg_two\n",
                                            include_files={"/bar": "spam\nbar\n", "/baz": "baz"})
        response = self.client.get(reverse("fwprofile-diff", args=(profile1.slug, profile2.slug)))

        self.assertContains(response, "-foo", status_code=200)
        self.assertContains(response, "-bar", status_code=200)
        self.assertContains(response, "+spam", status_code=200)
        self.assertContains(response, "+baz", status_code=200)

        self.assertContains(response, "+pkg_one", status_code=200)
        self.assertContains(response, "-pkg_three", status_code=200)
