# NUSA-RG

> Dibuat oleh PADZ-PRD · 20261018 · Bahasa: Indonesia
> Direvisi 20261022 agar sesuai dengan rilis berjalan (versi 1.3.0) dan
> dokumentasi di [README.md](README.md).

## Daftar Isi

1. Ringkasan Produk (s01)
2. Pernyataan Masalah (s02)
3. Tujuan & Metrik Keberhasilan (s03)
4. Persona Pengguna (s04)
5. Lingkup Produk (s05)
6. Persyaratan Fungsional (s06)
7. Persyaratan Non‑Fungsional, Keamanan, dan Pembaruan (s07)
8. Arsitektur Sistem (s08)
9. Model Data, Penyimpanan, & API (s09)
10. Logging & Audit (s10)
11. Antarmuka CLI & Pengalaman Pengguna (s11)
12. Kriteria Penerimaan (s12)
13. Jadwal & Milestone (s13)

## Ringkasan Produk

NUSA-RG adalah solusi asisten pemrograman berbasis Command Line Interface (CLI) yang dioptimalkan khusus untuk ekosistem Termux pada perangkat Android dengan arsitektur ARM. Produk ini hadir untuk menjembatani celah antara pengembangan kode di lingkungan terminal mobile dengan kemampuan kecerdasan buatan tingkat lanjut. Nilai utama dari sistem ini terletak pada pendekatan Hybrid LLM, di mana pengguna dapat memilih antara efisiensi API eksternal seperti OpenAI atau Groq, maupun privasi penuh melalui eksekusi model lokal menggunakan llama.cpp.

Kekuatan utama produk ini adalah implementasi Retrieval-Augmented Generation (RAG). Fitur ini memungkinkan asisten untuk tidak hanya menjawab pertanyaan umum, tetapi juga mengindeks seluruh struktur file dalam proyek lokal pengguna. Dengan kemampuan ini, asisten dapat mengambil potongan kode (snippets) yang relevan dari direktori proyek dan menggunakannya sebagai konteks tambahan saat menghasilkan jawaban. Hal ini memastikan bahwa saran kode, debugging, dan penjelasan arsitektur yang diberikan sangat spesifik terhadap basis kode yang sedang dikerjakan oleh pengguna di perangkat Android mereka, tanpa perlu meninggalkan lingkungan terminal.

Rilis berjalan menambahkan empat kemampuan yang tidak ada pada versi awal. Pertama, katalog provider dari [models.dev](https://models.dev): 232 provider dan 8.602 model tersimpan sebagai cuplikan lokal, 209 di antaranya siap dipakai hanya dengan satu kunci API, dan tiap provider punya logo yang digambar di terminal. Kedua, percakapan yang bisa dilanjutkan: setiap `nusa-rg chat` menyimpan sesinya sendiri, dan `nusa-rg chat --session <id>` melanjutkan percakapan itu. Ketiga, jawaban yang mengalir: jawaban provider dikirim token demi token lewat SSE dan dirender menjadi panel Markdown di terminal. Keempat, penghematan token: gaya jawaban "caveman", kompresor keluaran perintah bawaan, dan rtk sebagai pemadatan opsional.

## Pernyataan Masalah

Pengembangan perangkat lunak di dalam Termux memberikan fleksibilitas tinggi bagi pengguna Android, namun terdapat hambatan signifikan dalam hal dukungan asistensi coding. Saat ini, pengguna yang bekerja dengan proyek lokal seringkali harus berpindah antar aplikasi (context switching) antara terminal Termux dan browser atau aplikasi chat AI eksternal. Masalah utamanya adalah Large Language Model (LLM) umum tidak memiliki akses ke struktur file dan isi kode yang berada di dalam storage lokal Termux, sehingga jawaban yang diberikan seringkali terlalu generik dan tidak relevan dengan konteks proyek yang sedang dikembangkan.

Ketiadaan asisten berbasis terminal yang mampu melakukan indeksasi file lokal membuat proses debugging dan navigasi kode menjadi lambat. Pengguna harus menyalin kode secara manual ke dalam prompt AI, yang tidak hanya tidak efisien tetapi juga berisiko terhadap privasi jika kode sensitif dikirim ke cloud tanpa filter. Solusi yang tersedia di pasar saat ini mayoritas berbasis Graphical User Interface (GUI) yang berat atau memerlukan proses instalasi yang sangat kompleks dan tidak stabil pada lingkungan Android/ARM. Hal ini menciptakan kebutuhan mendesak akan alat yang ringan, terintegrasi penuh dengan CLI, dan mampu memahami konteks lokal secara otomatis.

Dua masalah tambahan muncul dari pemakaian sehari-hari. Pertama, biaya token: setiap jawaban panjang dan setiap keluaran perintah yang mentah-mentah masuk ke konteks, sehingga tagihan naik dan jawaban pendek ikut mahal. Kedua, ketergantungan alat luar: alat pemadat keluaran seperti rtk sering tidak bisa dijalankan di Termux karena binernya dibangun untuk platform lain, dan ketika itu terjadi, alat yang semestinya membantu justru menggagalkan perintahnya sendiri.

## Tujuan & Metrik Keberhasilan

Tujuan utama dari pengembangan NUSA-RG adalah menyediakan alat bantu coding yang terintegrasi, cepat, dan mudah diakses bagi pengguna Termux. Keberhasilan implementasi akan diukur melalui metrik konkret berikut:

*   **Kemudahan Instalasi dan Aksesibilitas**
    *   FR-01: Sistem harus dapat diinstal melalui satu baris perintah `pkg install termux-nusa-rg` [ASUMSI] paket tersedia di repository komunitas atau melalui script instalasi otomatis.
    *   AC-01: Proses instalasi selesai tanpa error pada Termux versi 0.118 ke atas dalam waktu kurang dari 120 detik pada koneksi internet stabil.

*   **Kapasitas Hybrid LLM**
    *   FR-02: Mendukung integrasi minimal satu provider API eksternal (OpenAI atau Groq) dan satu mesin eksekusi lokal (llama.cpp).
    *   AC-02: Pengguna dapat beralih antara mode API dan mode lokal melalui file konfigurasi tanpa perlu melakukan instalasi ulang komponen inti.

*   **Performa Retrieval RAG**
    *   FR-03: Sistem harus mampu melakukan indexing dan retrieval konteks dari file proyek lokal secara otomatis.
    *   AC-03: Latency waktu antara pengiriman query hingga hasil retrieval konteks muncul di terminal harus kurang dari 2 detik per query untuk proyek dengan ukuran hingga 50 MB [ASUMSI] menggunakan SQLite FTS5.

*   **Kepuasan Pengguna**
    *   FR-04: Mencapai tingkat penerimaan yang tinggi dari target pengguna utama (pemula coding).
    *   AC-04: Skor kepuasan pengguna mencapai minimal 80% berdasarkan survei pasca-penggunaan yang mencakup aspek kemudahan penggunaan dan akurasi jawaban kontekstual.

## Persona Pengguna

Produk ini dirancang untuk pengguna yang mengandalkan ekosistem Android sebagai lingkungan pengembangan ringan. Berikut adalah detail persona pengguna:

*   **Si Pembelajar Mandiri (Beginner Coder)**
    *   **Profil:** Individu yang baru mempelajari bahasa pemrograman (seperti Python atau JavaScript) dan menggunakan Termux karena tidak memiliki akses ke laptop atau lebih menyukai mobilitas.
    *   **Tujuan:** Memahami sintaksis kode, memperbaiki error dengan cepat, dan mendapatkan penjelasan konsep pemrograman tanpa harus berpindah aplikasi ke browser.
    *   **Titik Masalah:** Sering mengalami *context switching* yang mengganggu fokus saat harus menyalin error dari terminal ke browser untuk mencari solusi.
*   **Pengembang Hobbyist (Android Power User)**
    *   **Profil:** Pengguna yang terbiasa dengan Linux/Unix dan menggunakan Termux untuk membangun proyek kecil, otomatisasi script, atau mengelola server melalui SSH.
    *   **Tujuan:** Mempercepat proses penulisan kode dengan bantuan AI yang memahami struktur folder dan keterkaitan antar file dalam proyek lokal mereka.
    *   **Titik Masalah:** Kesulitan mengelola proyek yang mulai kompleks karena asisten AI umum tidak memiliki akses ke file lokal di dalam storage Termux.
*   **Mahasiswa Teknik Informatika (CS Student)**
    *   **Profil:** Mahasiswa yang membutuhkan lingkungan coding portabel untuk mengerjakan tugas kuliah atau eksperimen cepat di sela-sela jadwal kampus.
    *   **Tujuan:** Memiliki asisten coding yang efisien, ringan, dan dapat bekerja secara offline (via model lokal) saat tidak ada akses internet stabil.
    *   **Titik Masalah:** Ketergantungan pada perangkat berat (laptop) untuk mendapatkan fitur *intelligent completion* atau analisis kode yang mendalam.

## Lingkup Produk

Bagian ini mendefinisikan batasan fitur yang akan dikembangkan pada rilis pertama untuk memastikan fokus pengembangan tetap terjaga.

**Fitur yang Termasuk (In-Scope):**
*   **Antarmuka Chat CLI:** Implementasi interaksi berbasis teks melalui terminal Termux, termasuk mode interaktif (chat loop) dan mode perintah tunggal.
*   **Integrasi Hybrid LLM:**
    *   Konektor API untuk layanan eksternal (OpenAI dan Groq) menggunakan protokol HTTP/REST.
    *   Integrasi binary `llama.cpp` untuk menjalankan model lokal dalam format GGUF pada arsitektur ARM64.
*   **Modul Local Project RAG:**
    *   Sistem pemindaian file (file scanner) untuk membaca teks dari direktori proyek.
    *   Implementasi indeksasi lokal menggunakan SQLite FTS5 [ASUMSI] untuk pencarian cepat.
    *   Mekanisme *retrieval* untuk mengambil potongan kode (snippets) yang paling relevan berdasarkan query pengguna.
*   **Manajemen Konfigurasi:** Sistem pengaturan melalui file YAML tunggal yang terletak di direktori home pengguna untuk menyimpan preferensi model dan path proyek.
*   **Katalog Provider:** Cuplikan katalog models.dev yang disimpan lokal, penampil katalog di terminal, dan logo provider yang digambar sebagai sel Braille.
*   **Sesi Percakapan:** Penyimpanan percakapan per id di direktori state, dengan riwayat yang dapat dilanjutkan pada sesi berikutnya.
*   **Rantai Failover:** Rangkaian provider cadangan yang dicoba berurutan ketika provider aktif gagal.
*   **Alat Token:** Gaya jawaban telegraphic, kompresor keluaran perintah bawaan, dan dukungan rtk sebagai pemadatan opsional.
*   **Pembaruan Mandiri:** Perintah `nusa-rg update` yang memeriksa checkout sumber terhadap repositori resmi sebelum menarik perubahan.

**Fitur yang Tidak Termasuk (Out-of-Scope):**
*   **Antarmuka Grafis (GUI):** Tidak ada pengembangan aplikasi Android berbasis layar atau web-dashboard; seluruh interaksi dilakukan di terminal.
*   **Integrasi IDE Eksternal:** Tidak menyediakan plugin untuk VS Code, Vim, atau Nano; asisten bekerja sebagai aplikasi mandiri di CLI.
*   **Dukungan Arsitektur Non-ARM:** Produk tidak dioptimalkan untuk x86_64 atau arsitektur selain ARM64 yang didukung oleh Termux.
*   **Sinkronisasi Cloud:** Tidak ada fitur sinkronisasi indeks atau konfigurasi antar perangkat melalui cloud.

## Persyaratan Fungsional

Persyaratan fungsional berikut mendefinisikan perilaku sistem yang harus diimplementasikan untuk memenuhi kebutuhan pengguna.

**1. CLI Chat Interface**
*   **FR-05:** Sistem harus menyediakan perintah `nusa-rg chat` untuk memulai sesi percakapan interaktif.
    *   **AC-05:** Pengguna dapat mengirim pesan dan menerima respon dari LLM dalam satu layar terminal.
    *   **AC-06:** Sistem mendukung input multi-baris menggunakan karakter escape atau kombinasi tombol tertentu sebelum pesan dikirim.
*   **FR-06:** Sistem harus menyediakan perintah `nusa-rg --help` untuk menampilkan daftar perintah dan opsi penggunaan.
    *   **AC-07:** Dokumentasi bantuan menampilkan deskripsi singkat untuk setiap command (`chat`, `index`, `config`).

**2. Hybrid LLM Access**
*   **FR-07:** Sistem harus mampu beralih antara mode API Eksternal dan Mode Lokal melalui konfigurasi.
    *   **AC-08:** Saat mode API dipilih, sistem mengirimkan request ke endpoint OpenAI/Groq menggunakan API Key yang valid.
    *   **AC-09:** Saat mode Lokal dipilih, sistem memanggil binary `llama.cpp` dan memuat model GGUF dari path yang ditentukan.
*   **FR-08:** Sistem harus melakukan validasi konektivitas sebelum mengirim query ke API eksternal.
    *   **AC-10:** Sistem menampilkan pesan error yang jelas jika koneksi internet terputus atau API Key tidak valid.

**3. Local Project RAG**
*   **FR-09:** Sistem harus mampu mengindeks file dalam direktori proyek melalui perintah `nusa-rg index <path>`.
    *   **AC-11:** Sistem memindai semua file teks (misal: `.py`, `.js`, `.cpp`, `.txt`) dan menyimpannya ke dalam database SQLite lokal.
    *   **AC-12:** Proses indeksasi untuk proyek dengan [ASUMSI] 100 file harus selesai dalam waktu kurang dari 30 detik.
*   **FR-10:** Sistem harus melakukan retrieval konteks secara otomatis sebelum mengirim prompt ke LLM.
    *   **AC-13:** Sistem mengambil top-3 snippet paling relevan dari database indeks berdasarkan kemiripan kata kunci query.
    *   **AC-14:** Snippet yang diambil disertakan dalam prompt sebagai konteks tambahan untuk LLM.

**4. Prompt Customization & Configuration**
*   **FR-11:** Sistem harus memungkinkan pengguna mengatur *system prompt* untuk mengubah perilaku asisten.
    *   **AC-15:** Perubahan pada field `system_prompt` di `config.yaml` langsung diterapkan pada sesi chat berikutnya.
*   **FR-12:** Sistem harus mengelola konfigurasi melalui file `~/.nusa-rg/config.yaml`.
    *   **AC-16:** File konfigurasi menyimpan parameter: `model_provider`, `api_provider`, `api_base_url`, `api_model`, `api_key` (referensi keystore), `provider_keys`, `fallback_providers`, `local_model_path`, `local_llama_bin`, `default_project_path`, `system_prompt`, `response_style`, `session_history_turns`, `max_context_snippets`, `chunk_lines`, `chunk_overlap_lines`, `max_file_bytes`, `ignore_dirs`, `ignore_globs`, `request_timeout`, `max_tokens`, `temperature`, `command_timeout`, `command_output_limit`, `command_use_rtk`, `command_compress`, `update_remote`, dan `log_level`.
    *   **AC-17:** Sistem dapat membuat file konfigurasi default secara otomatis jika file tersebut belum ditemukan saat aplikasi pertama kali dijalankan.

**5. Katalog Provider dan Logo**
*   **FR-17: Katalog Provider**
    *   Sistem menyertakan cuplikan katalog [models.dev](https://models.dev) berisi provider, endpoint, variabel kunci, dan modelnya, sehingga katalog tetap bisa dibaca tanpa jaringan.
    *   `nusa-rg providers` menyediakan sub-perintah `list`, `show`, `models`, `icon`, dan `refresh`.
    *   Kunci API dapat disimpan per provider, baik di keystore terenkripsi maupun lewat variabel lingkungan yang dicatat models.dev.
    *   **AC-42:** `nusa-rg providers list` menampilkan seluruh provider dari katalog lokal tanpa akses jaringan, dan `nusa-rg providers refresh` menggantinya dengan cuplikan baru dari models.dev.
    *   **AC-43:** `nusa-rg config set api_key --provider <id> --secret` menyimpan kunci provider tertentu di keystore, dan `config show` tidak pernah menampilkannya sebagai teks biasa.
*   **FR-18: Logo Provider di Terminal**
    *   Setiap provider memiliki logo di registry pada alamat `/logos/{provider}.svg`; logo digambar di terminal sebagai sel Braille karena terminal tidak dapat menampilkan SVG.
    *   Berkas SVG diambil sekali dan disimpan di `~/.nusa-rg/logos`, lalu setiap entri katalog memakai warna khas yang ditentukan oleh id provider.
    *   **AC-44:** `nusa-rg providers list` menggambar logo setiap provider sebagai karakter Unicode, dan `nusa-rg providers icon <id>` menggambar logo satu provider tanpa menampilkan alamat berkas.
    *   **AC-45:** `NUSA_RG_NO_LOGOS=1` atau `providers list --no-icons` membuat katalog tampil sebagai tabel ringkas tanpa mengunduh apa pun.

**6. Sesi Percakapan yang Bisa Dilanjutkan**
*   **FR-19: Penyimpanan Sesi**
    *   Setiap `nusa-rg chat` membuat sesi percakapan sendiri dan menyimpannya di `~/.nusa-rg/sessions/<id>.json`; percakapan yang tidak terjadi tidak menghasilkan berkas.
    *   Berkas sesi hanya ditulis bila ada proyek yang terindeks dan percakapan benar-benar berlangsung; sesi yang dipanggil manual dengan `--session <id>` selalu disimpan.
    *   `nusa-rg chat --session <id>` melanjutkan sesi tersebut dan mengirim riwayat giliran sebelumnya sebagai konteks.
    *   **AC-46:** Setelah `nusa-rg chat` diakhiri, perintah untuk melanjutkan sesi beserta id-nya dicetak; `nusa-rg session list` menampilkan sesi yang benar-benar berisi percakapan.
    *   **AC-47:** Melanjutkan sesi dengan `--session <id>` membuat model menerima giliran sebelumnya sebagai konteks prompt.
*   **FR-20: Perintah Slash**
    *   Di dalam sesi, perintah `/exit`, `/quit`, `/clear`, `/session`, `/caveman`, `/update`, `/help`, dan baris yang diawali `!` tersedia; `/clear` juga mengosongkan riwayat sesi yang berjalan.
    *   **AC-48:** `/session list` dan `/session show` menampilkan sesi yang tersimpan tanpa keluar dari prompt.

**7. Failover Antar Provider**
*   **FR-21: Rantai Provider Cadangan**
    *   `fallback_providers` berisi daftar `id` atau `id:model` yang dicoba berurutan ketika provider aktif gagal; provider tanpa kunci, tanpa model, atau tanpa endpoint OpenAI-compatible dilewati dengan alasannya dicatat pada log.
    *   **AC-49:** Saat provider utama gagal, provider berikutnya menjawab dan giliran itu menyebut provider yang menjawab; `nusa-rg status` mencetak seluruh rantai.

**8. Jawaban Langsung dan Render Terminal**
*   **FR-22: Streaming dan Render**
    *   Jawaban provider yang mendukung SSE dikirim token demi token, dan cuplikan retrieval ditampilkan sebelum jawaban mulai mengalir.
    *   Markdown dirender menjadi panel terminal: blok kode berwarna sintaks, tabel berbingkai, serta daftar, daftar tugas, dan catatan kaki bertanda.
    *   **AC-50:** `nusa-rg chat` menampilkan jawaban secara bertahap tanpa menunggu model selesai, dan `nusa-rg chat --no-stream` menunggu jawaban utuh.

**9. Penghematan Token**
*   **FR-23: Gaya Caveman dan Kompresor Perintah**
    *   `response_style: caveman` menambahkan aturan ringkas ke system prompt tanpa mengubah kode, path, angka, identifier, maupun pesan error.
    *   Keluaran perintah diperpendek oleh kompresor bawaan ketika rtk tidak dipakai atau tidak dapat dijalankan, dengan aturan per jenis alat, dan selalu diberi penanda berapa baris yang dibuang.
    *   **AC-51:** `nusa-rg config set response_style caveman` dan `nusa-rg config set command_compress off` jeweils mengubah gaya jawaban dan pemadatan keluaran perintah.
    *   **AC-52:** Perintah yang dijalankan tetap berjalan dan keluarannya tetap sampai ke model ketika rtk terpasang tetapi tidak dapat dijalankan.

**10. Perintah pada Proyek Terindeks**
*   **FR-24: Lokasi Kerja Perintah**
    *   Perintah yang diketik pengguna dijalankan di direktori proyek yang terindeks, bukan di direktori tempat asisten dimulai, dan direktori kerja dicetak bersama keluarannya.
    *   **AC-53:** `!ls` di dalam sesi menampilkan isi proyek yang terindeks, dan `nusa-rg run --project <path>` memakai path yang disebutkan.

**11. Pembaruan Mandiri**
*   **FR-25: Self-Update**
    *   `nusa-rg update` hanya menarik dari repositori resmi; checkout yang menunjuk URL lama tetap diterima, dan remote tanpa tag rilis dibandingkan lewat commit branch.
    *   **AC-54:** Checkout yang `origin`-nya bukan repositori resmi ditolak dengan pesan yang menyebut remote yang terdeteksi.

## Persyaratan Non‑Fungsional, Keamanan, dan Pembaruan

Bagian ini menetapkan standar kualitas, batasan teknis, dan protokol keamanan untuk memastikan NUSA-RG berjalan stabil dan aman di lingkungan Android.

**1. Performa dan Kompatibilitas**
* **NFR-01: Kompatibilitas Lingkungan**: Sistem harus dapat berjalan sepenuhnya pada Termux versi 0.118 atau yang lebih baru pada perangkat Android dengan arsitektur ARM64.
    * **AC-18**: Aplikasi dapat diinstal dan dijalankan tanpa error dependensi pada Android 11, 12, 13, dan 14 [ASUMSI].
* **NFR-02: Latensi Respons**: Proses retrieval dokumen lokal harus selesai dalam waktu ≤ 2 detik, dan latency API eksternal ≤ 1 detik (tidak termasuk waktu generate token dari LLM).
    * **AC-19**: Pengujian pada direktori dengan 100 file menunjukkan waktu pencarian snippet ≤ 2 detik.
* **NFR-03: Efisiensi Penyimpanan**: Total ukuran instalasi inti harus $< 500 MB. Jika menggunakan model lokal llama.cpp 7B, total ruang yang dibutuhkan adalah $< 2 GB.
    * **AC-20**: Verifikasi ukuran folder `/data/data/com.termux/files/home/.nusa-rg` setelah instalasi.
* **NFR-04: Keandalan Sistem**: Sistem harus memiliki mekanisme *graceful recovery* sehingga indeks proyek tidak korup setelah terjadi crash atau force-close Termux.
    * **AC-21**: Sistem dapat memuat kembali indeks SQLite FTS5 setelah proses dimatikan secara paksa tanpa perlu re-indeksasi total.

**2. Keamanan Data dan Akses**
* **SEC-01: Enkripsi Kredensial**: Kunci API tidak boleh disimpan dalam bentuk plaintext.
    * **AC-22**: File `config.yaml` hanya menyimpan referensi kunci (`keystore://`), sementara nilai asli terenkripsi dengan AES-256-GCM di `~/.nusa-rg/keystore.bin`. Implementasi memakai pustaka `cryptography` dan kunci master `0600` di dalam sandbox Android, menyediakan jaminan yang sama dengan `termux-keystore` yang memang belum terbit sebagai paket Termux; penggantiannya cukup dilakukan di `nusa_rg/crypto.py`.
* **SEC-02: Validasi Input**: Semua input pengguna harus melalui proses sanitasi untuk mencegah *command injection* ke shell Termux dan *prompt injection* ke LLM.
    * **AC-23**: Karakter berbahaya seperti `;`, `&&`, `|` pada input chat tidak akan dieksekusi sebagai perintah shell.
* **SEC-03: Privasi Logging**: Log aplikasi harus menyensor token API, kunci privat, dan snippet kode sensitif. File log disimpan dengan izin akses 600.
    * **AC-24**: Pemeriksaan file log menunjukkan bahwa token API diganti dengan mask `***MASKED***`.
* **SEC-04: Proteksi Indeks**: Database indeks proyek disimpan dengan izin file 600 dan mendukung enkripsi opsional menggunakan passphrase pengguna.
    * **AC-25**: Upaya akses file `.db` indeks oleh user non-owner di lingkungan multi-user (jika ada) akan ditolak oleh sistem file.
* **SEC-05: Integritas Pembaruan**: Dependensi native seperti binary `llama.cpp` harus diverifikasi menggunakan checksum SHA-256 sebelum diinstal.
    * **AC-26**: Sistem menolak instalasi binary jika hash file yang diunduh tidak cocok dengan manifest resmi.
* **SEC-10: Batas Keluaran Perintah**: Keluaran perintah yang masuk ke prompt harus dibatasi ukurannya, diberi penanda, dan diperlakukan sebagai data yang tidak tepercaya.
    * **AC-55**: Keluaran perintah yang melebihi batas byte dipotong dengan bagian atas dan bawah yang dipertahankan, dan tidak pernah diperlakukan sebagai instruksi.
* **SEC-11: Bukti Manipulasi Kredensial**: Entri keystore memakai nama alias sebagai *associated data* AEAD sehingga perubahan pada nama atau isi entri membuat autentikasi gagal.
    * **AC-56**: Entri keystore yang namanya diubah atau isinya diedit ditolak saat dibaca.
* **SEC-12: Kuatan terhadap Prompt Injection**: Penanda peran, pembatas milik sendiri, dan kalimat pengoverride yang ditemukan pada berkas terindeks atau keluaran perintah dinetralkan sebelum mencapai prompt.
    * **AC-57**: Teks yang mencoba mengambil alih peran atau meniru penanda internal tidak muncul apa adanya di prompt yang dikirim ke model.

**3. Standar Teknis dan Implementasi**
* **NFR-05: Stack Teknologi**: Menggunakan Python 3.10+, library `click` untuk CLI, `PyYAML` untuk konfigurasi, `markdown2` untuk penguraian Markdown, dan SQLite FTS5 untuk mesin pencarian.
* **NFR-06: Desain Modular**: Arsitektur harus memisahkan logika CLI, LLM Client, RAG Module, dan Logging agar memudahkan pemeliharaan.
    * **AC-27**: Penggantian library LLM client tidak boleh mempengaruhi logika indexing pada RAG Module.
* **NFR-07: Dokumentasi**: Menyediakan manual penggunaan (`man nusa-rg`), README berbahasa Inggris dan Indonesia, serta panduan konfigurasi keamanan.
* **NFR-08: Keserasian Terminal**: Tampilan terminal memakai palet dan bentuk yang sama antara perintah `nusa-rg` dan skrip pemasang: emblem yang sama, chip berwarna, dan gelombang status yang sama.
    * **AC-58:** `nusa-rg --help` dan `./install.sh` menampilkan emblem dan warna yang sama.
* **NFR-09: Operasi Luring Jaringan**: Katalog provider, logo, dan pembaruan harus tetap dapat dibaca atau dijalankan tanpa jaringan; jaringannya hanya dibutuhkan untuk langkah yang memang memerlukannya.
    * **AC-59:** `nusa-rg providers list` dan `nusa-rg chat` tetap berfungsi tanpa koneksi internet.

## Arsitektur Sistem

NUSA-RG mengadopsi arsitektur modular yang dirancang untuk efisiensi sumber daya pada perangkat mobile. Alur kerja sistem dimulai dari **CLI Frontend** yang menerima input pengguna. Input ini kemudian diproses oleh **Command Parser** (berbasis library `click`) untuk menentukan apakah pengguna ingin melakukan chat, mengindeks proyek, menjalankan perintah, menelusuri katalog provider, mengelola sesi, atau mengubah konfigurasi.

Setelah perintah divalidasi, kendali berpindah ke **Core Engine**. Core Engine bertindak sebagai orkestrator utama yang mengelola dua jalur eksekusi LLM. Jalur pertama adalah **API Client**, yang melakukan request HTTP ke provider eksternal yang menggunakan protokol OpenAI chat-completions. Jalur kedua adalah **Local LLM Runner**, yang berinteraksi langsung dengan binary `llama.cpp` untuk menjalankan model GGUF secara lokal di CPU/GPU perangkat Android. Kedua jalur dapat dibungkus **Failover Client**, yang mencoba daftar provider secara berurutan.

Untuk memberikan konteks proyek, Core Engine memanggil **RAG Module**. Modul ini bekerja dalam empat tahap:
1. **File Scanner**: Memindai direktori proyek lokal dan memfilter file berdasarkan ukuran, nama, dan pola yang diabaikan.
2. **Index Builder**: Memecah konten file menjadi chunk-chunk kecil dan menyimpannya ke dalam **SQLite FTS5** dengan tokenizer `unicode61 remove_diacritics 2` untuk pencarian teks cepat; berkas yang tidak berubah dilewati berdasarkan mtime.
3. **Retriever**: Mengambil snippet kode yang paling relevan berdasarkan query pengguna menggunakan peringkat BM25.
4. **Prompt Composer**: Menggabungkan snippet yang ditemukan dengan query asli pengguna dan *system prompt* untuk membentuk instruksi final yang dikirim ke LLM, dengan setiap snippet diberi label `path:line`.

Di luar jalur RAG, ada tiga modul pendukung. **Catalogue** menyimpan cuplikan katalog models.dev dan menyediakan daftar provider, model, key variable, dan logo. **Session Store** menyimpan percakapan per id sebagai berkas JSON, lengkap dengan gaya jawaban yang dipakai. **Command Runner** menjalankan perintah yang diketik pengguna melalui rtk bila rtk tersedia dan bisa dijalankan, atau melalui kompresor bawaan bila tidak, tanpa pernah melewati shell.

Seluruh operasional ini didukung oleh **Configuration Layer** yang membaca file `~/.nusa-rg/config.yaml` untuk menentukan endpoint API, path model lokal, dan pengaturan indeks. Terakhir, **Logging & Error Handling** terpusat di Core Engine untuk memastikan setiap kegagalan (seperti timeout API atau kekurangan RAM saat menjalankan model lokal) ditangani dengan pesan error yang informatif tanpa membocorkan data sensitif.

## Model Data, Penyimpanan, & API

Sistem menggunakan kombinasi penyimpanan berbasis file dan database relasional ringan untuk memastikan performa tinggi di lingkungan Termux.

**1. Struktur Penyimpanan Lokal**

| Komponen | Tipe | Lokasi / Format | Deskripsi |
| :--- | :--- | :--- | :--- |
| **Indeks Proyek** | SQLite FTS5 | `~/.nusa-rg/index.db` | Menyimpan tokenisasi konten file, metadata (path, line number), dan skor relevansi. |
| **Konfigurasi** | YAML | `~/.nusa-rg/config.yaml` | Menyimpan endpoint API, path model lokal, daftar folder dan pola yang diabaikan, dan preferensi model. |
| **Kredensial** | Encrypted | `~/.nusa-rg/keystore.bin` | Menyimpan API Key terenkripsi AES-256-GCM; `config.yaml` hanya berisi referensi `keystore://`. |
| **Kunci Master** | File | `~/.nusa-rg/master.key` | Kunci acak per instalasi, mode 600, menurunkan kunci keystore lewat scrypt. |
| **Sesi Percakapan** | JSON | `~/.nusa-rg/sessions/<id>.json` | Menyimpan giliran user dan assisten beserta gaya jawaban, mode 600. |
| **Logo Provider** | SVG | `~/.nusa-rg/logos/<id>.svg` | Salinan logo dari models.dev yang digambar di terminal, mode 600. |
| **Katalog Provider** | JSON | `~/.nusa-rg/catalog.json` | Cuplikan katalog hasil `providers refresh`, menggantikan cuplikan bawaan. |
| **Application Log** | Text | `~/.nusa-rg/logs/app.log` | Menyimpan jejak eksekusi dengan izin akses 600 dan mekanisme rotasi setiap 10 MB [ASUMSI]. |

**2. Antarmuka API Internal (Inter-Module)**

Untuk menjaga modularitas, komunikasi antar modul dilakukan melalui kontrak API internal sebagai berikut:

| Endpoint / Method | Input Payload | Output Response | Deskripsi |
| :--- | :--- | :--- | :--- |
| `RAG.retrieve()` | `{ query: string, project_path: string }` | `{ snippets: [string], scores: [float], sources: [string] }` | Mengambil potongan kode paling relevan dari database SQLite FTS5. |
| `LLM.generate()` | `{ prompt: string, context: string, stream: boolean, history: [message] }` | `{ text: string, usage: { prompt_tokens: int, completion_tokens: int } }` | Mengirim prompt ke API eksternal atau llama.cpp dan mengembalikan jawaban. |
| `Config.get()` | `{ key: string }` | `{ value: any }` | Mengambil nilai konfigurasi dari YAML atau keystore secara aman. |
| `Catalogue.search()` | `{ text: string, compatible_only: boolean }` | `{ providers: [Provider] }` | Mencari provider pada katalog lokal. |
| `Session.load()` / `Session.save()` | `{ id: string, turns: [turn] }` | `{ session: Session }` | Memuat dan menyimpan percakapan per id. |
| `Command.run()` | `{ argv: [string], cwd: string }` | `{ output: string, exit_code: int }` | Menjalankan perintah yang diketik pengguna, lewat rtk atau kompresor bawaan. |

**3. Integrasi API Eksternal**

| Provider | Method | Endpoint | Fungsi |
| :--- | :--- | :--- | :--- |
| **OpenAI / Groq / katalog models.dev** | POST | `/v1/chat/completions` | Mengirimkan *composed prompt* dan menerima jawaban teks; katalog bawaan memuat 232 provider, 209 di antaranya siap dipakai. |
| **Provider OpenAI-compatible lain** | POST | `/v1/chat/completions` | Dapat dipakai dengan `api_base_url` yang diisi manual, misalnya Ollama Cloud. |

## Logging & Audit

Bagian ini menetapkan standar pencatatan aktivitas sistem untuk memastikan transparansi operasional tanpa mengorbankan privasi data pengguna atau keamanan kredensial.

*   **SEC-06: Masking Data Sensitif pada Log**
    *   Sistem dilarang keras menulis query lengkap, kunci API, token, atau snippet kode sumber ke dalam file log.
    *   Data yang dicatat hanya berupa metadata: timestamp (ISO 8601), level log (INFO, WARN, ERROR), dan hash SHA-256 dari query pengguna untuk keperluan pelacakan tanpa menyimpan teks asli.
    *   **AC-32**: Verifikasi bahwa tidak ada string yang cocok dengan pola API Key (misal: `sk-...`) atau isi file project yang muncul dalam file `.log`.

*   **SEC-07: Proteksi Penyimpanan Log**
    *   Log harus disimpan di direktori privat pengguna Termux (contoh: `~/.nusa-rg/logs/app.log`).
    *   File log wajib memiliki izin akses `600` (read/write hanya untuk pemilik file) untuk mencegah akses oleh aplikasi lain di lingkungan Android.
    *   **AC-33**: Perintah `ls -l` pada file log menunjukkan izin `-rw-------`.

*   **SEC-08: Mekanisme Rotasi Log**
    *   Untuk mencegah penggunaan storage yang berlebihan, sistem harus menerapkan rotasi log otomatis.
    *   Log akan dirotasi jika ukuran file mencapai 10 MB [ASUMSI], dengan menyimpan maksimal 5 file arsip lama sebelum menghapus yang tertua.
    *   **AC-34**: Sistem secara otomatis membuat `app.log.1` saat `app.log` mencapai batas 10 MB.

*   **SEC-09: Fasilitas Audit Akses**
    *   Sistem harus mencatat setiap upaya perubahan pada file konfigurasi (`config.yaml`) dan proses pembuatan/penghapusan indeks proyek.
    *   Log audit harus mencatat waktu kejadian dan hasil operasi (SUCCESS/FAILED).
    *   **AC-35**: Setiap kali perintah `nusa-rg config` dijalankan, terdapat entri log yang mencatat perubahan parameter konfigurasi.

## Antarmuka CLI & Pengalaman Pengguna

Interaksi pengguna dirancang untuk meminimalkan hambatan (friction) dengan memanfaatkan standar CLI yang intuitif dan memberikan feedback visual yang jelas meskipun berada di lingkungan terminal.

*   **FR-13: Struktur Perintah Utama**
    *   Sistem menyediakan entry point tunggal `nusa-rg` dengan sub-perintah berikut:
        *   `nusa-rg chat`: Memulai sesi percakapan interaktif dengan LLM, atau menjawab satu pertanyaan lalu keluar.
        *   `nusa-rg index`: Melakukan scanning dan indeksasi direktori proyek yang ditentukan.
        *   `nusa-rg config`: Mengatur API key, pemilihan model, dan path proyek.
        *   `nusa-rg run`: Menjalankan perintah terminal dan, dengan `--ask`, menjawab berdasarkan keluarannya.
        *   `nusa-rg providers`: Menelusuri katalog provider, model, dan logonya.
        *   `nusa-rg session`: Mengelola percakapan tersimpan.
        *   `nusa-rg status`: Melaporkan provider, model, gaya, rantai failover, indeks, dan konektivitas.
        *   `nusa-rg update`: Memperbarui checkout sumber ke rilis terbaru.
        *   `nusa-rg doctor`: Melakukan pemeriksaan pemasangan dan keamanan.
    *   **AC-36**: Menjalankan `nusa-rg --help` menampilkan daftar perintah di atas beserta deskripsi singkatnya.

*   **FR-14: Mode Interaktif (Chat Session)**
    *   Saat masuk ke mode `chat`, sistem menampilkan prompt berwarna (misal: hijau untuk User, biru untuk Assistant) untuk membedakan peran.
    *   Sistem mendukung input multi-line (menggunakan karakter escape seperti `\n` atau deteksi baris kosong) agar pengguna dapat memasukkan blok kode.
    *   Pengguna dapat mengakhiri sesi dengan mengetikkan perintah `/exit` atau menggunakan shortcut `Ctrl+D`.
    *   **AC-37**: Pengguna dapat memasukkan 3 baris kode berbeda dalam satu prompt dan mengirimkannya sebagai satu pesan utuh.

*   **FR-15: Feedback Visual dan Indikator Status**
    *   Sistem menampilkan *loading spinner* atau animasi teks "Thinking..." saat menunggu respon dari LLM (baik API maupun lokal) untuk menandakan aplikasi tidak hang.
    *   Hasil retrieval dari RAG module harus ditampilkan dengan highlight (misal: menggunakan warna kuning atau italic) pada bagian snippet yang paling relevan sebelum jawaban LLM muncul.
    *   **AC-38**: Spinner muncul dalam waktu < 500 ms setelah pengguna menekan Enter.

*   **FR-16: Sistem Bantuan Terintegrasi**
    *   Perintah `nusa-rg --help` atau `-h` harus menampilkan dokumentasi singkat mengenai sintaks perintah, contoh penggunaan, dan daftar flag yang tersedia.
    *   **AC-39**: Dokumentasi help mencakup contoh perintah lengkap seperti `nusa-rg index /home/project/my-app`.

*   **FR-26: Gaya Jawaban yang Dapat Dimatikan**
    *   Gaya caveman dan kompresor keluaran perintah diaktifkan atau dimatikan lewat konfigurasi, dengan kata `on` dan `off` yang diterima.
    *   **AC-60**: `nusa-rg config set response_style caveman` dan `nusa-rg config set command_compress off` menyimpan nilai boolean yang benar dan berlaku pada perintah berikutnya.

## Kriteria Penerimaan

Kriteria ini menjadi standar absolut untuk menentukan apakah fitur telah selesai dikembangkan dan layak untuk dirilis ke tahap produksi.

*   **AC-40: Keberhasilan Instalasi**
    *   Proses instalasi melalui satu baris perintah `pkg install termux-nusa-rg` (atau script installer `.sh`) harus berjalan tanpa error pada Termux versi 0.118 ke atas di perangkat ARM64.

*   **AC-41: Fungsionalitas Dasar Chat**
    *   CLI mampu menampilkan prompt chat, mengirimkan input pengguna ke LLM (OpenAI/Groq/llama.cpp), dan menampilkan balasan teks secara streaming atau utuh tanpa crash.

*   **AC-28: Performa Indeksasi Proyek**
    *   Sistem mampu melakukan indeksasi terhadap direktori proyek yang berisi lebih dari 100 file teks/kode (misal: `.py`, `.js`, `.cpp`) dalam waktu kurang dari 30 detik [ASUMSI] pada perangkat dengan spesifikasi menengah.

*   **AC-29: Akurasi Retrieval RAG**
    *   Pada set uji internal yang terdiri dari 20 pertanyaan spesifik tentang kode proyek, sistem harus mampu mengambil snippet yang relevan dengan skor kemiripan ≥ 0.7 [ASUMSI] dalam 80% kasus.

*   **AC-30: Fleksibilitas Perpindahan Model**
    *   Pengguna dapat mengubah model dari `external` (API) ke `local` (llama.cpp) melalui `nusa-rg config` dan langsung menggunakannya dalam sesi chat berikutnya tanpa perlu melakukan restart aplikasi atau reboot terminal.

*   **AC-31: Keamanan Kredensial**
    *   Tidak ada API key atau password yang tersimpan dalam bentuk plaintext di dalam file `config.yaml` atau log; semua kredensial harus terenkripsi atau disimpan di keystore terenkripsi.

*   **AC-61: Kesiapan Rilis**
    *   Seluruh suite pengujian lulus tanpa akses jaringan maupun API key, dan skrip pemasang dipakai pada perangkat Termux ARM64.

## Jadwal & Milestone

Bagian ini menetapkan lini masa pengembangan NUSA-RG, dari prototipe awal hingga rilis berjalan. Tanggal di bawah mengikuti riwayat rilis repository.

| ID Milestone | Milestone | Tanggal Target | Aktivitas Utama & Deliverables | Kriteria Keberhasilan |
| :--- | :--- | :--- | :--- | :--- |
| **MS-01** | **MVP Prototype** | 2026-10-18 | Pengembangan CLI chat dasar, integrasi API OpenAI/Groq, dan implementasi modul indeksasi file menggunakan SQLite FTS5. | CLI dapat mengirim query ke API eksternal dan mengambil snippet file lokal dengan akurasi dasar. |
| **MS-02** | **Hybrid LLM Support** | 2026-10-18 | Integrasi binary `llama.cpp` untuk eksekusi model lokal, konfigurasi dinamis lewat `config.yaml`, dan pengelolaan memori untuk model 7B. | Pengguna dapat beralih antara API eksternal dan model lokal tanpa instalasi ulang. |
| **MS-03** | **Offline Update & Remote Guard** | 2026-10-18 | Perintah pembaruan mandiri, penjaga remote, verifikasi checksum, dan perbaikan pembacaan remote (rilis 1.1.0 sampai 1.3.0). | Pembaruan hanya menarik dari repositori resmi dan menolak checkout asing. |
| **MS-04** | **Catalogue, rtk, Caveman** | 2026-10-18 | Katalog provider models.dev, kunci per provider, rantai failover, dukungan rtk, dan gaya jawaban caveman. | Pengguna dapat memilih provider dari katalog dan memangkas token keluaran perintah. |
| **MS-05** | **Terminal UI & Live Streaming** | 2026-10-20 | Emblem, chip status, gelombang spinner, dan jawaban yang mengalir token demi token lewat SSE. | Terminal menampilkan lambang, chip, dan jawaban bertahap yang konsisten. |
| **MS-06** | **Sessions, Provider Logos, Self-Update** | 2026-10-21 | Sesi percakapan yang bisa dilanjutkan, logo provider yang digambar sebagai sel Braille, dan penjaga remote yang mengikuti repositori berjalan. | Percakapan dapat dilanjutkan dengan `--session`, dan katalog menampilkan logo setiap provider. |
| **MS-07** | **Documentation & Built-in Compressor** | 2026-10-22 | README berbahasa Inggris dan Indonesia, logo repo, dan kompresor keluaran perintah bawaan sebagai pengganti rtk yang tidak bisa jalan. | Dokumentasi sesuai implementasi dan perintah tetap jalan tanpa rtk. |

**Catatan Implementasi Milestone:**
1. **Ketergantungan Teknis:** Milestone MS-02 sangat bergantung pada ketersediaan binary `llama.cpp` yang teroptimasi untuk arsitektur ARM64 Android. Jika terjadi kendala kompilasi, target tanggal dapat bergeser maksimal 14 hari.
2. **Pengujian Beta:** Pada MS-04, pengujian akan difokuskan pada konsumsi RAM saat menjalankan model lokal untuk memastikan aplikasi tidak dihentikan oleh *Android Low Memory Killer* (LMK).
3. **Verifikasi GA:** Rilis GA hanya akan dilakukan jika seluruh kriteria penerimaan (Acceptance Criteria) yang didefinisikan pada bagian sebelumnya telah terpenuhi 100%.
