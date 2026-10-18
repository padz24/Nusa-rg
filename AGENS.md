# NUSA-RG

> Dibuat oleh PADZ-PRD · 20261018 · Bahasa: Indonesia

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

NUSA-RG adalah solusi asisten pemrograman berbasis Command Line Interface (CLI) yang dioptimalkan secara khusus untuk ekosistem Termux pada perangkat Android dengan arsitektur ARM. Produk ini hadir untuk menjembatani celah antara pengembangan kode di lingkungan terminal mobile dengan kemampuan kecerdasan buatan tingkat lanjut. Nilai utama dari sistem ini terletak pada pendekatan Hybrid LLM, di mana pengguna dapat memilih antara efisiensi API eksternal seperti OpenAI atau Groq, maupun privasi penuh melalui eksekusi model lokal menggunakan llama.cpp.

Kekuatan utama produk ini adalah implementasi Retrieval-Augmented Generation (RAG). Fitur ini memungkinkan asisten untuk tidak hanya menjawab pertanyaan umum, tetapi juga mengindeks seluruh struktur file dalam proyek lokal pengguna. Dengan kemampuan ini, asisten dapat mengambil potongan kode (snippets) yang relevan dari direktori proyek dan menggunakannya sebagai konteks tambahan saat menghasilkan jawaban. Hal ini memastikan bahwa saran kode, debugging, dan penjelasan arsitektur yang diberikan sangat spesifik terhadap basis kode yang sedang dikerjakan oleh pengguna di perangkat Android mereka, tanpa perlu meninggalkan lingkungan terminal.

## Pernyataan Masalah

Pengembangan perangkat lunak di dalam Termux memberikan fleksibilitas tinggi bagi pengguna Android, namun terdapat hambatan signifikan dalam hal dukungan asistensi coding. Saat ini, pengguna yang bekerja dengan proyek lokal seringkali harus berpindah antar aplikasi (context switching) antara terminal Termux dan browser atau aplikasi chat AI eksternal. Masalah utamanya adalah Large Language Model (LLM) umum tidak memiliki akses ke struktur file dan isi kode yang berada di dalam storage lokal Termux, sehingga jawaban yang diberikan seringkali terlalu generik dan tidak relevan dengan konteks proyek yang sedang dikembangkan.

Ketiadaan asisten berbasis terminal yang mampu melakukan indeksasi file lokal membuat proses debugging dan navigasi kode menjadi lambat. Pengguna harus menyalin kode secara manual ke dalam prompt AI, yang tidak hanya tidak efisien tetapi juga berisiko terhadap privasi jika kode sensitif dikirim ke cloud tanpa filter. Solusi yang tersedia di pasar saat ini mayoritas berbasis Graphical User Interface (GUI) yang berat atau memerlukan proses instalasi yang sangat kompleks dan tidak stabil pada lingkungan Android/ARM. Hal ini menciptakan kebutuhan mendesak akan alat yang ringan, terintegrasi penuh dengan CLI, dan mampu memahami konteks lokal secara otomatis.

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
    *   **Tujuan:** Memahami sintaksis kode, memperbaiki error secara cepat, dan mendapatkan penjelasan konsep pemrograman tanpa harus berpindah aplikasi ke browser.
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
    *   Mekanisme *retrieval* untuk mengambil potongan kode (snippets) yang relevan berdasarkan query pengguna.
*   **Manajemen Konfigurasi:** Sistem pengaturan melalui file YAML tunggal yang terletak di direktori home pengguna untuk menyimpan preferensi model dan path proyek.

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
    *   **AC-11:** Sistem memindai semua file teks (mis. `.py`, `.js`, `.cpp`, `.txt`) dan menyimpannya ke dalam database SQLite lokal.
    *   **AC-12:** Proses indeksasi untuk proyek dengan [ASUMSI] 100 file harus selesai dalam waktu kurang dari 30 detik.
*   **FR-10:** Sistem harus melakukan retrieval konteks secara otomatis sebelum mengirim prompt ke LLM.
    *   **AC-13:** Sistem mengambil top-3 snippet paling relevan dari database indeks berdasarkan kemiripan kata kunci query.
    *   **AC-14:** Snippet yang diambil disertakan dalam prompt sebagai konteks tambahan untuk LLM.

**4. Prompt Customization & Configuration**
*   **FR-11:** Sistem harus memungkinkan pengguna mengatur *system prompt* untuk mengubah perilaku asisten.
    *   **AC-15:** Perubahan pada field `system_prompt` di `config.yaml` langsung diterapkan pada sesi chat berikutnya.
*   **FR-12:** Sistem harus mengelola konfigurasi melalui file `~/.nusa-rg/config.yaml`.
    *   **AC-16:** File konfigurasi menyimpan parameter: `api_key`, `model_provider`, `local_model_path`, dan `default_project_path`.
    *   **AC-17:** Sistem dapat membuat file konfigurasi default secara otomatis jika file tersebut belum ditemukan saat aplikasi pertama kali dijalankan.

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
* **SEC-01: Enkripsi Kredensial**: Kunci API (OpenAI/Groq) tidak boleh disimpan dalam bentuk plaintext. Penyimpanan wajib menggunakan `termux-crypto` dan `termux-keystore`.
    * **AC-22**: File `config.yaml` hanya menyimpan referensi kunci, sementara nilai asli terenkripsi di keystore sistem.
* **SEC-02: Validasi Input**: Semua input pengguna harus melalui proses sanitasi untuk mencegah *command injection* ke shell Termux dan *prompt injection* ke LLM.
    * **AC-23**: Karakter berbahaya seperti `;`, `&&`, `|` pada input chat tidak akan dieksekusi sebagai perintah shell.
* **SEC-03: Privasi Logging**: Log aplikasi harus menyensor token API, kunci privat, dan snippet kode sensitif. File log disimpan dengan izin akses 600.
    * **AC-24**: Pemeriksaan file log menunjukkan bahwa token API diganti dengan mask `***MASKED***`.
* **SEC-04: Proteksi Indeks**: Database indeks proyek disimpan dengan izin file 600 dan mendukung enkripsi opsional menggunakan passphrase pengguna.
    * **AC-25**: Upaya akses file `.db` indeks oleh user non-owner di lingkungan multi-user (jika ada) akan ditolak oleh sistem file.
* **SEC-05: Integritas Pembaruan**: Dependensi native seperti binary `llama.cpp` harus diverifikasi menggunakan checksum SHA-256 sebelum diinstal.
    * **AC-26**: Sistem menolak instalasi binary jika hash file yang diunduh tidak cocok dengan manifest resmi.

**3. Standar Teknis dan Implementasi**
* **NFR-05: Stack Teknologi**: Menggunakan Python 3.10+, library `click` untuk CLI, `PyYAML` untuk konfigurasi, dan SQLite FTS5 untuk mesin pencarian.
* **NFR-06: Desain Modular**: Arsitektur harus memisahkan logika CLI, LLM Client, RAG Module, dan Logging agar memudahkan pemeliharaan.
    * **AC-27**: Penggantian library LLM client tidak boleh mempengaruhi logika indexing pada RAG Module.
* **NFR-07: Dokumentasi**: Menyediakan manual penggunaan (`man nusa-rg`) dan panduan konfigurasi keamanan.

## Arsitektur Sistem

NUSA-RG mengadopsi arsitektur modular yang dirancang untuk efisiensi sumber daya pada perangkat mobile. Alur kerja sistem dimulai dari **CLI Frontend** yang menerima input pengguna. Input ini kemudian diproses oleh **Command Parser** (berbasis library `click`) untuk menentukan apakah pengguna ingin melakukan chat, mengindeks proyek, atau mengubah konfigurasi.

Setelah perintah divalidasi, kendali berpindah ke **Core Engine**. Core Engine bertindak sebagai orkestrator utama yang mengelola dua jalur eksekusi LLM. Jalur pertama adalah **API Client**, yang melakukan request HTTP ke provider eksternal seperti OpenAI atau Groq. Jalur kedua adalah **Local LLM Runner**, yang menginteraksi langsung dengan binary `llama.cpp` untuk menjalankan model GGUF secara lokal di CPU/GPU perangkat Android.

Untuk memberikan konteks proyek, Core Engine memanggil **RAG Module**. Modul ini bekerja dalam empat tahap:
1. **File Scanner**: Memindai direktori proyek lokal dan memfilter file berdasarkan ekstensi yang didukung (misal: `.py`, `.js`, `.cpp`).
2. **Index Builder**: Memecah konten file menjadi chunk-chunk kecil dan menyimpannya ke dalam **SQLite FTS5** untuk pencarian teks cepat.
3. **Retriever**: Mengambil snippet kode yang paling relevan berdasarkan query pengguna menggunakan teknik *keyword-based search* atau *vector similarity* [ASUMSI].
4. **Prompt Composer**: Menggabungkan snippet yang ditemukan dengan query asli pengguna dan *system prompt* untuk membentuk instruksi final yang dikirim ke LLM.

Seluruh operasional ini didukung oleh **Configuration Layer** yang membaca file `~/.nusa-rg/config.yaml` untuk menentukan endpoint API, path model lokal, dan pengaturan indeks. Terakhir, **Logging & Error Handling** terpusat di Core Engine untuk memastikan setiap kegagalan (seperti timeout API atau kekurangan RAM saat menjalankan model lokal) ditangani dengan pesan error yang informatif tanpa membocorkan data sensitif.

## Model Data, Penyimpanan, & API

Sistem menggunakan kombinasi penyimpanan berbasis file dan database relasional ringan untuk memastikan performa tinggi di lingkungan Termux.

**1. Struktur Penyimpanan Lokal**

| Komponen | Tipe | Lokasi / Format | Deskripsi |
| :--- | :--- | :--- | :--- |
| **Indeks Proyek** | SQLite FTS5 | `~/.nusa-rg/index.db` | Menyimpan tokenisasi konten file, metadata (path, line number), dan skor relevansi. |
| **Konfigurasi** | YAML | `~/.nusa-rg/config.yaml` | Menyimpan endpoint API, path model lokal, daftar folder yang diabaikan (`.gitignore`), dan preferensi model. |
| **Kredensial** | Encrypted | `termux-keystore` | Menyimpan API Key terenkripsi yang hanya bisa diakses oleh aplikasi melalui API keystore Android. |
| **Application Log** | Text | `~/.nusa-rg/logs/app.log` | Menyimpan jejak eksekusi dengan izin akses 600 dan mekanisme rotasi setiap 10 MB [ASUMSI]. |

**2. Antarmuka API Internal (Inter-Module)**

Untuk menjaga modularitas, komunikasi antar modul dilakukan melalui kontrak API internal sebagai berikut:

| Endpoint / Method | Input Payload | Output Response | Deskripsi |
| :--- | :--- | :--- | :--- |
| `RAG.retrieve()` | `{ query: string, project_path: string }` | `{ snippets: [string], scores: [float], sources: [string] }` | Mengambil potongan kode paling relevan dari database SQLite FTS5. |
| `LLM.generate()` | `{ prompt: string, context: string, stream: boolean }` | `{ text: string, usage: { prompt_tokens: int, completion_tokens: int } }` | Mengirim prompt ke API eksternal atau llama.cpp dan mengembalikan jawaban. |
| `Config.get()` | `{ key: string }` | `{ value: any }` | Mengambil nilai konfigurasi dari YAML atau keystore secara aman. |

**3. Integrasi API Eksternal**

| Provider | Method | Endpoint | Fungsi |
| :--- | :--- | :--- | :--- |
| **OpenAI / Groq** | POST | `/v1/chat/completions` | Mengirimkan *composed prompt* dan menerima jawaban teks berbasis model GPT atau Llama-3. |

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
        *   `nusa-rg chat`: Memulai sesi percakapan interaktif dengan LLM.
        *   `nusa-rg index`: Melakukan scanning dan indeksasi direktori proyek yang ditentukan.
        *   `nusa-rg config`: Mengatur API key, pemilihan model, dan path proyek.
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

## Kriteria Penerimaan

Kriteria ini menjadi standar absolut untuk menentukan apakah fitur telah selesai dikembangkan dan layak untuk dirilis ke tahap produksi.

*   **AC-40: Keberhasilan Instalasi**
    *   Proses instalasi melalui satu baris perintah `pkg install termux-nusa-rg` (atau script installer `.sh`) harus berjalan tanpa error pada Termux versi 0.118 ke atas di perangkat ARM64.

*   **AC-41: Fungsionalitas Dasar Chat**
    *   CLI mampu menampilkan prompt chat, mengirimkan input pengguna ke LLM (OpenAI/Groq/llama.cpp), dan menampilkan balasan teks secara streaming atau utuh tanpa crash.

*   **AC-28: Performa Indeksasi Proyek**
    *   Sistem mampu melakukan indeksasi terhadap direktori proyek yang berisi lebih dari 100 file teks/kode (misal: `.py`, `.js`, `.cpp`) dalam waktu kurang dari 30 detik [ASUMSI] pada perangkat dengan spesifikasi menengah.

*   **AC-29: Akurasi Retrieval RAG**
    *   Pada set uji internal yang terdiri dari 20 pertanyaan spesifik tentang kode proyek, sistem harus mampu mengambil snippet yang relevan dengan skor cosine similarity ≥ 0.7 [ASUMSI] dalam 80% kasus.

*   **AC-30: Fleksibilitas Perpindahan Model**
    *   Pengguna dapat mengubah model dari `external` (API) ke `local` (llama.cpp) melalui `nusa-rg config` dan langsung menggunakannya dalam sesi chat berikutnya tanpa perlu melakukan restart aplikasi atau reboot terminal.

*   **AC-31: Keamanan Kredensial**
    *   Tidak ada API key atau password yang tersimpan dalam bentuk plaintext di dalam file `config.yaml` atau log; semua kredensial harus terenkripsi menggunakan `termux-crypto` atau disimpan di `termux-keystore`.

## Jadwal & Milestone

Bagian ini menetapkan lini masa pengembangan NUSA-RG, mulai dari pengembangan prototipe awal hingga rilis stabil (General Availability). Jadwal ini dirancang untuk memastikan setiap komponen inti—terutama integrasi Hybrid LLM dan modul RAG—diuji secara bertahap pada berbagai perangkat Android ARM64.

| ID Milestone | Milestone | Tanggal Target | Aktivitas Utama & Deliverables | Kriteria Keberhasilan |
| :--- | :--- | :--- | :--- | :--- |
| **MS-01** | **MVP Prototype** | 2024-12-01 | Pengembangan CLI chat dasar, integrasi API OpenAI/Groq, dan implementasi modul indeksasi file sederhana menggunakan SQLite FTS5. | CLI dapat mengirim query ke API eksternal dan mengambil snippet file lokal dengan akurasi dasar. |
| **MS-02** | **Hybrid LLM Support** | 2025-02-15 | Integrasi binary `llama.cpp` untuk eksekusi model lokal, pembuatan sistem konfigurasi dinamis via `config.yaml`, dan manajemen memori untuk model 7B. | Pengguna dapat beralih antara API eksternal dan model lokal tanpa melakukan instalasi ulang aplikasi. |
| **MS-03** | **Performance Tuning** | 2025-04-01 | Optimasi latency retrieval agar < 2 detik [ASUMSI], kompresi database indeks, dan pengujian kompatibilitas pada minimal 5 versi Android berbeda. | Latency retrieval konsisten di bawah 2 detik untuk proyek dengan > 100 file pada perangkat ARM64. |
| **MS-04** | **Beta Release & User Testing** | 2025-05-15 | Distribusi paket beta ke komunitas Termux, pengumpulan feedback melalui survei, dan perbaikan bug kritis berdasarkan laporan pengguna. | Skor kepuasan pengguna mencapai ≥ 80% dan tidak ada bug kategori *blocker* yang tersisa. |
| **MS-05** | **GA (General Availability)** | 2025-07-01 | Finalisasi dokumentasi lengkap (User Guide & Security Policy), optimasi paket instalasi `pkg`, dan rilis versi stabil 1.0.0. | Paket dapat diinstal melalui satu baris perintah `pkg install termux-nusa-rg` secara stabil. |

**Catatan Implementasi Milestone:**
1. **Ketergantungan Teknis:** Milestone MS-02 sangat bergantung pada ketersediaan binary `llama.cpp` yang teroptimasi untuk arsitektur ARM64 Android. Jika terjadi kendala kompilasi, target tanggal dapat bergeser maksimal 14 hari.
2. **Pengujian Beta:** Pada MS-04, pengujian akan difokuskan pada konsumsi RAM saat menjalankan model lokal untuk memastikan aplikasi tidak dihentikan oleh *Android Low Memory Killer* (LMK).
3. **Verifikasi GA:** Rilis GA hanya akan dilakukan jika seluruh kriteria penerimaan (Acceptance Criteria) yang didefinisikan pada bagian sebelumnya telah terpenuhi 100%.
