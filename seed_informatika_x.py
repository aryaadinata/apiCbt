import sys
import json
sys.path.insert(0, r"C:\Users\USER\Documents\Arya Adinata\Project WEB\apiCbt")
from database import get_db

questions_data = [
    {
        "num": 1,
        "content": "Dalam berpikir komputasional, proses memecah masalah yang kompleks menjadi bagian-bagian yang lebih kecil dan lebih mudah dikelola disebut...",
        "options": [
            {"key": "A", "text": "Dekomposisi", "image_url": None, "match": None},
            {"key": "B", "text": "Abstraksi", "image_url": None, "match": None},
            {"key": "C", "text": "Pengenalan Pola", "image_url": None, "match": None},
            {"key": "D", "text": "Algoritma", "image_url": None, "match": None},
            {"key": "E", "text": "Evaluasi", "image_url": None, "match": None}
        ],
        "answer": "A",
        "explanation": "Dekomposisi adalah teknik memecah masalah kompleks menjadi sub-masalah yang lebih kecil agar lebih mudah diselesaikan."
    },
    {
        "num": 2,
        "content": "Seorang teknisi jaringan menganalisis data lalu lintas data dan menemukan bahwa kemacetan selalu terjadi pada jam 12.00 - 13.00 setiap hari kerja. Pilar computational thinking yang diterapkan teknisi tersebut adalah...",
        "options": [
            {"key": "A", "text": "Abstraksi", "image_url": None, "match": None},
            {"key": "B", "text": "Pengenalan Pola (Pattern Recognition)", "image_url": None, "match": None},
            {"key": "C", "text": "Dekomposisi", "image_url": None, "match": None},
            {"key": "D", "text": "Algoritma", "image_url": None, "match": None},
            {"key": "E", "text": "Pemodelan Data", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Menemukan pola keteraturan atau tren waktu kemacetan merupakan contoh penerapan Pattern Recognition."
    },
    {
        "num": 3,
        "content": "Saat merancang peta rute bus kota, desainer hanya menampilkan nama halte dan jalur utama tanpa menggambarkan pohon, gedung, atau lebar jalan sebenarnya. Prinsip berpikir komputasional yang digunakan adalah...",
        "options": [
            {"key": "A", "text": "Algoritma", "image_url": None, "match": None},
            {"key": "B", "text": "Dekomposisi", "image_url": None, "match": None},
            {"key": "C", "text": "Abstraksi", "image_url": None, "match": None},
            {"key": "D", "text": "Simulasi", "image_url": None, "match": None},
            {"key": "E", "text": "Automasi", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "Abstraksi fokus pada informasi relevan (halte & rute) dan mengabaikan detail yang tidak esensial."
    },
    {
        "num": 4,
        "content": "Urutan langkah-langkah logis dan terstruktur yang disusun secara sistematis untuk menyelesaikan suatu permasalahan disebut...",
        "options": [
            {"key": "A", "text": "Program", "image_url": None, "match": None},
            {"key": "B", "text": "Algoritma", "image_url": None, "match": None},
            {"key": "C", "text": "Variabel", "image_url": None, "match": None},
            {"key": "D", "text": "Pseudocode", "image_url": None, "match": None},
            {"key": "E", "text": "Flowchart", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Algoritma adalah deretan instruksi terurut dan terdefinisi dengan jelas untuk memecahkan masalah."
    },
    {
        "num": 5,
        "content": "Struktur data linier yang bekerja dengan prinsip LIFO (Last In First Out) di mana elemen terakhir yang dimasukkan akan menjadi elemen pertama yang dikeluarkan adalah...",
        "options": [
            {"key": "A", "text": "Queue", "image_url": None, "match": None},
            {"key": "B", "text": "Stack (Tumpukan)", "image_url": None, "match": None},
            {"key": "C", "text": "Array", "image_url": None, "match": None},
            {"key": "D", "text": "Linked List", "image_url": None, "match": None},
            {"key": "E", "text": "Tree", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Stack menggunakan prinsip LIFO (Last In First Out)."
    },
    {
        "num": 6,
        "content": "Fitur 'Undo' (membatalkan aksi terakhir) dan tombol 'Back' pada browser internet mengimplementasikan struktur data...",
        "options": [
            {"key": "A", "text": "Queue", "image_url": None, "match": None},
            {"key": "B", "text": "Stack", "image_url": None, "match": None},
            {"key": "C", "text": "Tree", "image_url": None, "match": None},
            {"key": "D", "text": "Graph", "image_url": None, "match": None},
            {"key": "E", "text": "Hash Table", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Fitur Undo dan Back browser menyimpan riwayat tindakan terakhir di bagian atas tumpukan (Stack)."
    },
    {
        "num": 7,
        "content": "Struktur data yang menerapkan prinsip FIFO (First In First Out), di mana data yang pertama kali masuk akan diproses pertama kali, disebut...",
        "options": [
            {"key": "A", "text": "Queue (Antrean)", "image_url": None, "match": None},
            {"key": "B", "text": "Stack", "image_url": None, "match": None},
            {"key": "C", "text": "Binary Tree", "image_url": None, "match": None},
            {"key": "D", "text": "Heap", "image_url": None, "match": None},
            {"key": "E", "text": "Graph", "image_url": None, "match": None}
        ],
        "answer": "A",
        "explanation": "Queue (antrean) memproses elemen yang masuk lebih dulu terlebih dahulu (FIFO)."
    },
    {
        "num": 8,
        "content": "Manakah sistem berikut yang paling tepat menggunakan konsep struktur data Queue?",
        "options": [
            {"key": "A", "text": "Tumpukan piring di restoran", "image_url": None, "match": None},
            {"key": "B", "text": "Riwayat panggilan keluar di smartphone", "image_url": None, "match": None},
            {"key": "C", "text": "Antrean pencetakan dokumen pada printer spooler", "image_url": None, "match": None},
            {"key": "D", "text": "Pengecekan tanda kurung pada kode program", "image_url": None, "match": None},
            {"key": "E", "text": "Fungsi tombol kembali di halaman web", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "Printer spooler mencetak dokumen sesuai urutan dokumen dikirimkan (antrean FIFO)."
    },
    {
        "num": 9,
        "content": "Struktur data hierarkis non-linier yang terdiri dari root, node anak (children), dan daun (leaf) seperti struktur direktori folder komputer adalah...",
        "options": [
            {"key": "A", "text": "Graph", "image_url": None, "match": None},
            {"key": "B", "text": "Tree (Pohon)", "image_url": None, "match": None},
            {"key": "C", "text": "Queue", "image_url": None, "match": None},
            {"key": "D", "text": "Array 2 Dimensi", "image_url": None, "match": None},
            {"key": "E", "text": "Stack", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Struktur direktori/folder file pada sistem operasi direpresentasikan dengan struktur data Tree."
    },
    {
        "num": 10,
        "content": "Dalam logika matematika dan informatika, proposisi majemuk 'P DAN Q' (P ∧ Q) hanya bernilai BENAR jika...",
        "options": [
            {"key": "A", "text": "Salah satu dari P atau Q bernilai benar", "image_url": None, "match": None},
            {"key": "B", "text": "P bernilai benar dan Q bernilai salah", "image_url": None, "match": None},
            {"key": "C", "text": "Baik P maupun Q keduanya bernilai benar", "image_url": None, "match": None},
            {"key": "D", "text": "Kedua proposisi bernilai salah", "image_url": None, "match": None},
            {"key": "E", "text": "P bernilai salah dan Q bernilai benar", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "Operasi konjungsi (AND) mensyaratkan kedua operand bernilai benar untuk menghasilkan nilai benar."
    },
    {
        "num": 11,
        "content": "Fitur pada aplikasi pengolah kata yang berfungsi untuk membuat surat massal atau sertifikat dengan format yang sama tetapi ditujukan ke data penerima yang berbeda disebut...",
        "options": [
            {"key": "A", "text": "Track Changes", "image_url": None, "match": None},
            {"key": "B", "text": "Mail Merge", "image_url": None, "match": None},
            {"key": "C", "text": "Macro", "image_url": None, "match": None},
            {"key": "D", "text": "Cross Reference", "image_url": None, "match": None},
            {"key": "E", "text": "Table of Contents", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Mail Merge mengintegrasikan dokumen master dengan data source untuk menghasilkan dokumen personalisasi massal."
    },
    {
        "num": 12,
        "content": "Teknologi integrasi aplikasi perkantoran yang memungkinkan objek spreadsheet disisipkan ke dalam dokumen pengolah kata dan otomatis terbarui saat file spreadsheet aslinya berubah disebut...",
        "options": [
            {"key": "A", "text": "OLE (Object Linking and Embedding)", "image_url": None, "match": None},
            {"key": "B", "text": "API Integration", "image_url": None, "match": None},
            {"key": "C", "text": "Hyperlink", "image_url": None, "match": None},
            {"key": "D", "text": "Screen Clipping", "image_url": None, "match": None},
            {"key": "E", "text": "Copy-Paste Static", "image_url": None, "match": None}
        ],
        "answer": "A",
        "explanation": "OLE (Object Linking and Embedding) memungkinkan penyematan objek hidup antar aplikasi perkantoran."
    },
    {
        "num": 13,
        "content": "Pada aplikasi spreadsheet, rumus yang digunakan untuk mencari data pada kolom tertentu secara vertikal berdasarkan kata kunci pencarian adalah...",
        "options": [
            {"key": "A", "text": "=HLOOKUP()", "image_url": None, "match": None},
            {"key": "B", "text": "=VLOOKUP()", "image_url": None, "match": None},
            {"key": "C", "text": "=INDEX_MATCH()", "image_url": None, "match": None},
            {"key": "D", "text": "=SEARCH()", "image_url": None, "match": None},
            {"key": "E", "text": "=LOOKUP_COL()", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "VLOOKUP (Vertical Lookup) mencari nilai kunci di kolom paling kiri dan mengambil nilai pada kolom indeks terkait."
    },
    {
        "num": 14,
        "content": "Jika di sel A1 terdapat angka 85, apa hasil dari rumus spreadsheet berikut: =IF(A1>=80, \"Sangat Baik\", IF(A1>=70, \"Baik\", \"Cukup\"))?",
        "options": [
            {"key": "A", "text": "Baik", "image_url": None, "match": None},
            {"key": "B", "text": "Sangat Baik", "image_url": None, "match": None},
            {"key": "C", "text": "Cukup", "image_url": None, "match": None},
            {"key": "D", "text": "#VALUE!", "image_url": None, "match": None},
            {"key": "E", "text": "85", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Karena 85 >= 80, kondisi pertama langsung terpenuhi dan mengembalikan 'Sangat Baik'."
    },
    {
        "num": 15,
        "content": "Rumus spreadsheet yang paling tepat untuk menghitung berapa banyak siswa yang mendapatkan nilai di atas 75 dalam rentang sel B2:B30 adalah...",
        "options": [
            {"key": "A", "text": "=COUNT(B2:B30, \">75\")", "image_url": None, "match": None},
            {"key": "B", "text": "=SUMIF(B2:B30, \">75\")", "image_url": None, "match": None},
            {"key": "C", "text": "=COUNTIF(B2:B30, \">75\")", "image_url": None, "match": None},
            {"key": "D", "text": "=COUNTA(B2:B30)", "image_url": None, "match": None},
            {"key": "E", "text": "=TOTALIF(B2:B30, \">75\")", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "COUNTIF menghitung frekuensi sel yang memenuhi kriteria tertentu (dalam hal ini '>75')."
    },
    {
        "num": 16,
        "content": "Layanan penyimpanan berkas berbasis awan (cloud storage) yang memungkinkan sinkronisasi otomatis dan kolaborasi berkas secara real-time adalah...",
        "options": [
            {"key": "A", "text": "Google Drive dan OneDrive", "image_url": None, "match": None},
            {"key": "B", "text": "RAM dan ROM", "image_url": None, "match": None},
            {"key": "C", "text": "Flashdisk dan Harddisk Eksternal", "image_url": None, "match": None},
            {"key": "D", "text": "BIOS dan CMOS", "image_url": None, "match": None},
            {"key": "E", "text": "Cache L1 dan L2", "image_url": None, "match": None}
        ],
        "answer": "A",
        "explanation": "Google Drive dan Microsoft OneDrive adalah layanan penyimpanan dan kolaborasi cloud terpopuler."
    },
    {
        "num": 17,
        "content": "Perangkat keras komputer yang berfungsi sebagai unit pemroses utama dan sering dianalogikan sebagai 'otak' komputer adalah...",
        "options": [
            {"key": "A", "text": "Motherboard", "image_url": None, "match": None},
            {"key": "B", "text": "CPU (Central Processing Unit)", "image_url": None, "match": None},
            {"key": "C", "text": "RAM", "image_url": None, "match": None},
            {"key": "D", "text": "Harddisk Drive", "image_url": None, "match": None},
            {"key": "E", "text": "Power Supply Unit", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "CPU bertanggung jawab memproses instruksi dan mengendalikan komputasi utama pada komputer."
    },
    {
        "num": 18,
        "content": "Bagian dari CPU yang bertugas melakukan operasi perhitungan matematika (seperti penjumlahan dan perkalian) serta operasi logika (seperti AND, OR, NOT) adalah...",
        "options": [
            {"key": "A", "text": "Control Unit (CU)", "image_url": None, "match": None},
            {"key": "B", "text": "Arithmetic Logic Unit (ALU)", "image_url": None, "match": None},
            {"key": "C", "text": "Register", "image_url": None, "match": None},
            {"key": "D", "text": "Cache Memory", "image_url": None, "match": None},
            {"key": "E", "text": "System Bus", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "ALU (Arithmetic Logic Unit) adalah modul eksekutif perhitungan matematika dan evaluasi logika."
    },
    {
        "num": 19,
        "content": "Bagian CPU yang bertugas mengambil instruksi dari memori (fetch), menerjemahkannya (decode), dan mengatur jalannya seluruh komponen komputer adalah...",
        "options": [
            {"key": "A", "text": "Arithmetic Logic Unit (ALU)", "image_url": None, "match": None},
            {"key": "B", "text": "Control Unit (CU)", "image_url": None, "match": None},
            {"key": "C", "text": "ROM", "image_url": None, "match": None},
            {"key": "D", "text": "Secondary Storage", "image_url": None, "match": None},
            {"key": "E", "text": "GPU", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Control Unit (CU) berfungsi sebagai pengendali alur instruksi dan penjadwalan siklus CPU."
    },
    {
        "num": 20,
        "content": "Karakteristik memori RAM (Random Access Memory) yang membedakannya dengan media penyimpanan permanen adalah sifatnya yang...",
        "options": [
            {"key": "A", "text": "Non-volatile (data tetap tersimpan saat komputer mati)", "image_url": None, "match": None},
            {"key": "B", "text": "Volatile (data hilang jika catu daya listrik terputus)", "image_url": None, "match": None},
            {"key": "C", "text": "Hanya dapat dibaca dan tidak bisa ditulis", "image_url": None, "match": None},
            {"key": "D", "text": "Memiliki kapasitas paling besar di antara semua memori", "image_url": None, "match": None},
            {"key": "E", "text": "Menggunakan piringan magnetik yang berputar", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "RAM bersifat volatile, artinya data di dalamnya hanya bertahan selama ada aliran daya listrik."
    },
    {
        "num": 21,
        "content": "Chip memori pada motherboard yang menyimpan instruksi dasar sistem saat pertama kali komputer dinyalakan (proses booting BIOS/UEFI) adalah...",
        "options": [
            {"key": "A", "text": "RAM", "image_url": None, "match": None},
            {"key": "B", "text": "ROM (Read Only Memory)", "image_url": None, "match": None},
            {"key": "C", "text": "Cache L3", "image_url": None, "match": None},
            {"key": "D", "text": "Virtual Memory", "image_url": None, "match": None},
            {"key": "E", "text": "Register", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "ROM menyimpan firmware BIOS/UEFI yang tidak hilang saat listrik padam (non-volatile)."
    },
    {
        "num": 22,
        "content": "Keunggulan utama Solid State Drive (SSD) dibandingkan dengan Hard Disk Drive (HDD) konvensional adalah...",
        "options": [
            {"key": "A", "text": "Kapasitas penyimpanan jauh lebih murah per gigabyte", "image_url": None, "match": None},
            {"key": "B", "text": "Menggunakan piringan magnetik berputar yang tahan banting", "image_url": None, "match": None},
            {"key": "C", "text": "Kecepatan baca-tulis jauh lebih tinggi dan tahan guncangan karena tanpa komponen mekanis", "image_url": None, "match": None},
            {"key": "D", "text": "Data akan terhapus otomatis jika tidak dialiri daya listrik", "image_url": None, "match": None},
            {"key": "E", "text": "Hanya dapat digunakan untuk menyimpan sistem operasi", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "SSD menggunakan chip flash memory tanpa bagian mekanis, menghasilkan akses data cepat dan tahan goncangan."
    },
    {
        "num": 23,
        "content": "Antarmuka sistem operasi modern yang menggunakan elemen visual seperti jendela (windows), ikon grafis, menu tarik-turun, dan kursor mouse dikenal sebagai...",
        "options": [
            {"key": "A", "text": "CLI (Command Line Interface)", "image_url": None, "match": None},
            {"key": "B", "text": "GUI (Graphical User Interface)", "image_url": None, "match": None},
            {"key": "C", "text": "VUI (Voice User Interface)", "image_url": None, "match": None},
            {"key": "D", "text": "TUI (Text User Interface)", "image_url": None, "match": None},
            {"key": "E", "text": "Batch Processing", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "GUI (Graphical User Interface) memudahkan pengguna berinteraksi dengan komputer lewat representasi visual."
    },
    {
        "num": 24,
        "content": "Antarmuka pengguna pada sistem operasi di mana pengguna berinteraksi dengan mengetikkan baris instruksi teks perintah (seperti Command Prompt atau Terminal) disebut...",
        "options": [
            {"key": "A", "text": "GUI", "image_url": None, "match": None},
            {"key": "B", "text": "CLI (Command Line Interface)", "image_url": None, "match": None},
            {"key": "C", "text": "API", "image_url": None, "match": None},
            {"key": "D", "text": "VUI", "image_url": None, "match": None},
            {"key": "E", "text": "BIOS", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "CLI adalah antarmuka interaksi berbasis pengetikan sintaks perintah."
    },
    {
        "num": 25,
        "content": "Manakah di bawah ini yang BUKAN merupakan fungsi utama dari sebuah Sistem Operasi (Operating System)?",
        "options": [
            {"key": "A", "text": "Mengatur manajemen memori dan alokasi CPU untuk proses", "image_url": None, "match": None},
            {"key": "B", "text": "Menyediakan antarmuka antara pengguna dengan perangkat keras", "image_url": None, "match": None},
            {"key": "C", "text": "Mengelola sistem berkas dan struktur penyimpanan sekunder", "image_url": None, "match": None},
            {"key": "D", "text": "Membuat dokumen presentasi dan laporan keuangan otomatis", "image_url": None, "match": None},
            {"key": "E", "text": "Mengendalikan komunikasi perangkat input/output melalui driver", "image_url": None, "match": None}
        ],
        "answer": "D",
        "explanation": "Membuat dokumen dan presentasi adalah tugas aplikasi produktivitas (application software), bukan OS."
    },
    {
        "num": 26,
        "content": "Kemampuan sistem operasi modern untuk menjalankan beberapa program atau aplikasi secara bersamaan (misal memutar lagu sambil mengetik dokumen) disebut...",
        "options": [
            {"key": "A", "text": "Multitasking", "image_url": None, "match": None},
            {"key": "B", "text": "Multi-threading", "image_url": None, "match": None},
            {"key": "C", "text": "Overclocking", "image_url": None, "match": None},
            {"key": "D", "text": "Virtual Memory", "image_url": None, "match": None},
            {"key": "E", "text": "Pipelining", "image_url": None, "match": None}
        ],
        "answer": "A",
        "explanation": "Multitasking memungkinkan sistem operasi menjalankan lebih dari satu tugas/aplikasi secara bersamaan."
    },
    {
        "num": 27,
        "content": "Nilai bilangan desimal dari bilangan biner 1011 (basis 2) adalah...",
        "options": [
            {"key": "A", "text": "9", "image_url": None, "match": None},
            {"key": "B", "text": "10", "image_url": None, "match": None},
            {"key": "C", "text": "11", "image_url": None, "match": None},
            {"key": "D", "text": "13", "image_url": None, "match": None},
            {"key": "E", "text": "15", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "1*2^3 + 0*2^2 + 1*2^1 + 1*2^0 = 8 + 0 + 2 + 1 = 11."
    },
    {
        "num": 28,
        "content": "Konversikan bilangan desimal 25 ke dalam bentuk bilangan biner!",
        "options": [
            {"key": "A", "text": "11001", "image_url": None, "match": None},
            {"key": "B", "text": "10101", "image_url": None, "match": None},
            {"key": "C", "text": "11100", "image_url": None, "match": None},
            {"key": "D", "text": "10011", "image_url": None, "match": None},
            {"key": "E", "text": "11010", "image_url": None, "match": None}
        ],
        "answer": "A",
        "explanation": "25 / 2 = 12 sisa 1; 12 / 2 = 6 sisa 0; 6 / 2 = 3 sisa 0; 3 / 2 = 1 sisa 1; 1 / 2 = 0 sisa 1. Hasil: 11001."
    },
    {
        "num": 29,
        "content": "Sistem bilangan heksadesimal berbasis 16 menggunakan simbol angka 0-9 dan huruf A-F. Huruf 'D' dalam heksadesimal setara dengan bilangan desimal...",
        "options": [
            {"key": "A", "text": "11", "image_url": None, "match": None},
            {"key": "B", "text": "12", "image_url": None, "match": None},
            {"key": "C", "text": "13", "image_url": None, "match": None},
            {"key": "D", "text": "14", "image_url": None, "match": None},
            {"key": "E", "text": "15", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "Dalam heksadesimal: A=10, B=11, C=12, D=13, E=14, F=15."
    },
    {
        "num": 30,
        "content": "Jaringan komputer yang menghubungkan komputer dan perangkat dalam cakupan geografis sempit seperti satu laboratorium komputer sekolah atau satu ruangan kantor disebut...",
        "options": [
            {"key": "A", "text": "LAN (Local Area Network)", "image_url": None, "match": None},
            {"key": "B", "text": "MAN (Metropolitan Area Network)", "image_url": None, "match": None},
            {"key": "C", "text": "WAN (Wide Area Network)", "image_url": None, "match": None},
            {"key": "D", "text": "PAN (Personal Area Network)", "image_url": None, "match": None},
            {"key": "E", "text": "SAN (Storage Area Network)", "image_url": None, "match": None}
        ],
        "answer": "A",
        "explanation": "LAN mencakup wilayah terbatas seperti gedung, sekolah, atau laboratorium."
    },
    {
        "num": 31,
        "content": "Topologi jaringan di mana semua komputer client terhubung ke satu perangkat konsentrator sentral (Switch/Hub), sehingga apabila satu kabel client putus jaringan lainnya tetap berfungsi normal adalah...",
        "options": [
            {"key": "A", "text": "Topologi Bus", "image_url": None, "match": None},
            {"key": "B", "text": "Topologi Ring", "image_url": None, "match": None},
            {"key": "C", "text": "Topologi Star (Bintang)", "image_url": None, "match": None},
            {"key": "D", "text": "Topologi Mesh", "image_url": None, "match": None},
            {"key": "E", "text": "Topologi Linier", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "Topologi Star memiliki titik pusat (switch/hub); kegagalan satu kabel node tidak memutus node lainnya."
    },
    {
        "num": 32,
        "content": "Perangkat keras jaringan yang bertugas menghubungkan dua atau lebih jaringan berbeda (misal jaringan LAN lokal dengan jaringan Internet global) serta memilih rute data terbaik adalah...",
        "options": [
            {"key": "A", "text": "Repeater", "image_url": None, "match": None},
            {"key": "B", "text": "Hub", "image_url": None, "match": None},
            {"key": "C", "text": "Router", "image_url": None, "match": None},
            {"key": "D", "text": "Switch Unmanaged", "image_url": None, "match": None},
            {"key": "E", "text": "Network Interface Card (NIC)", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "Router bekerja pada Layer 3 (Network) untuk merutekan paket data antar subnet/jaringan yang berbeda."
    },
    {
        "num": 33,
        "content": "Perbedaan mendasar antara protokol HTTP dan HTTPS dalam penjelajahan web adalah...",
        "options": [
            {"key": "A", "text": "HTTPS hanya dapat diakses melalui smartphone", "image_url": None, "match": None},
            {"key": "B", "text": "HTTPS menggunakan enkripsi SSL/TLS sehingga data aman dari penyadapan", "image_url": None, "match": None},
            {"key": "C", "text": "HTTP memiliki kecepatan transmisi data jauh lebih lambat daripada HTTPS", "image_url": None, "match": None},
            {"key": "D", "text": "HTTP hanya digunakan untuk mentransfer file video", "image_url": None, "match": None},
            {"key": "E", "text": "HTTPS tidak memerlukan koneksi internet untuk bekerja", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "HTTPS menyertakan lapisan keamanan enkripsi (SSL/TLS) untuk mengamankan data pengguna."
    },
    {
        "num": 34,
        "content": "Layanan pada jaringan internet yang berfungsi menerjemahkan nama domain yang mudah diingat manusia (seperti www.kemdikbud.go.id) menjadi alamat IP numerik komputer adalah...",
        "options": [
            {"key": "A", "text": "DHCP (Dynamic Host Configuration Protocol)", "image_url": None, "match": None},
            {"key": "B", "text": "DNS (Domain Name System)", "image_url": None, "match": None},
            {"key": "C", "text": "FTP (File Transfer Protocol)", "image_url": None, "match": None},
            {"key": "D", "text": "SMTP (Simple Mail Transfer Protocol)", "image_url": None, "match": None},
            {"key": "E", "text": "NAT (Network Address Translation)", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "DNS bertindak seperti buku telepon internet yang memetakan nama domain ke alamat IP."
    },
    {
        "num": 35,
        "content": "Protokol jaringan yang bertugas memberikan alamat IP secara otomatis kepada perangkat client saat terhubung ke jaringan Wi-Fi sekolah adalah...",
        "options": [
            {"key": "A", "text": "DNS", "image_url": None, "match": None},
            {"key": "B", "text": "DHCP", "image_url": None, "match": None},
            {"key": "C", "text": "HTTP", "image_url": None, "match": None},
            {"key": "D", "text": "SNMP", "image_url": None, "match": None},
            {"key": "E", "text": "SSH", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "DHCP (Dynamic Host Configuration Protocol) mengalokasikan IP address dinamis ke client secara otomatis."
    },
    {
        "num": 36,
        "content": "Struktur alamat IPv4 terdiri atas bilangan biner sepanjang 32-bit yang dikelompokkan ke dalam ... oktet yang dipisahkan oleh tanda titik.",
        "options": [
            {"key": "A", "text": "2 oktet", "image_url": None, "match": None},
            {"key": "B", "text": "4 oktet", "image_url": None, "match": None},
            {"key": "C", "text": "6 oktet", "image_url": None, "match": None},
            {"key": "D", "text": "8 oktet", "image_url": None, "match": None},
            {"key": "E", "text": "16 oktet", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "IPv4 terdiri dari 4 oktet (masing-masing 8 bit = total 32 bit), contohnya 192.168.1.1."
    },
    {
        "num": 37,
        "content": "Media transmisi data kabel yang menggunakan serat kaca sangat halus dan mengirimkan data dalam bentuk pulsa cahaya dengan kecepatan mendekati kecepatan cahaya adalah...",
        "options": [
            {"key": "A", "text": "Kabel UTP (Unshielded Twisted Pair)", "image_url": None, "match": None},
            {"key": "B", "text": "Kabel Coaxial", "image_url": None, "match": None},
            {"key": "C", "text": "Kabel Fiber Optik", "image_url": None, "match": None},
            {"key": "D", "text": "Kabel STP", "image_url": None, "match": None},
            {"key": "E", "text": "Kabel Telepon RJ-11", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "Fiber Optik mentransmisikan data menggunakan pembiasan cahaya, tahan interferensi elektromagnetik dan berkecepatan tinggi."
    },
    {
        "num": 38,
        "content": "Sistem keamanan jaringan yang memantau dan mengontrol lalu lintas data masuk dan keluar berdasarkan aturan keamanan yang telah ditetapkan untuk mencegah akses tidak sah disebut...",
        "options": [
            {"key": "A", "text": "Firewall", "image_url": None, "match": None},
            {"key": "B", "text": "Antivirus", "image_url": None, "match": None},
            {"key": "C", "text": "Spyware", "image_url": None, "match": None},
            {"key": "D", "text": "Adware", "image_url": None, "match": None},
            {"key": "E", "text": "Keylogger", "image_url": None, "match": None}
        ],
        "answer": "A",
        "explanation": "Firewall berfungsi sebagai dinding pertahanan penyaring lalu lintas jaringan sesuai kebijakan keamanan."
    },
    {
        "num": 39,
        "content": "Perbedaan mendasar antara 'Data' dan 'Informasi' dalam ilmu informatika adalah...",
        "options": [
            {"key": "A", "text": "Data selalu berupa angka, sedangkan informasi selalu berupa gambar", "image_url": None, "match": None},
            {"key": "B", "text": "Data adalah fakta mentah yang belum diolah, sedangkan informasi adalah data yang sudah diolah dan bermakna", "image_url": None, "match": None},
            {"key": "C", "text": "Data memiliki ukuran memori lebih kecil daripada informasi", "image_url": None, "match": None},
            {"key": "D", "text": "Data hanya dapat disimpan di harddisk, informasi di internet", "image_url": None, "match": None},
            {"key": "E", "text": "Tidak ada perbedaan antara data dan informasi", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Data merupakan kumpulan fakta mentah, ketika diproses dan diinterpretasikan menjadi informasi yang memiliki nilai guna."
    },
    {
        "num": 40,
        "content": "Contoh data kuantitatif dalam konteks data siswa di sekolah adalah...",
        "options": [
            {"key": "A", "text": "Warna kesukaan siswa", "image_url": None, "match": None},
            {"key": "B", "text": "Tinggi badan dan nilai ujian matematika siswa", "image_url": None, "match": None},
            {"key": "C", "text": "Hobi dan cita-cita siswa", "image_url": None, "match": None},
            {"key": "D", "text": "Nama lengkap dan asal sekolah menengah pertama", "image_url": None, "match": None},
            {"key": "E", "text": "Golongan darah siswa", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Data kuantitatif adalah data numerik yang dapat diukur atau dihitung nilainya."
    },
    {
        "num": 41,
        "content": "Dalam tahapan analisis data, aktivitas membuang data duplikat, memperbaiki format tanggal yang salah, dan menangani nilai kosong (missing values) disebut...",
        "options": [
            {"key": "A", "text": "Data Scraping", "image_url": None, "match": None},
            {"key": "B", "text": "Data Cleaning (Pembersihan Data)", "image_url": None, "match": None},
            {"key": "C", "text": "Data Mining", "image_url": None, "match": None},
            {"key": "D", "text": "Data Visualization", "image_url": None, "match": None},
            {"key": "E", "text": "Data Storage", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Data Cleaning adalah proses menyortir, memperbaiki atau membuang data inkonsisten/cacat sebelum dianalisis."
    },
    {
        "num": 42,
        "content": "Jenis grafik visualisasi yang paling tepat digunakan untuk menampilkan tren perkembangan suhu harian selama satu bulan penuh adalah...",
        "options": [
            {"key": "A", "text": "Pie Chart (Diagram Lingkaran)", "image_url": None, "match": None},
            {"key": "B", "text": "Line Chart (Grafik Garis)", "image_url": None, "match": None},
            {"key": "C", "text": "Bar Chart Horizontal", "image_url": None, "match": None},
            {"key": "D", "text": "Radar Chart", "image_url": None, "match": None},
            {"key": "E", "text": "Donut Chart", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Line chart ideal untuk menunjukkan pola perubahan data kontinu dari waktu ke waktu (time series)."
    },
    {
        "num": 43,
        "content": "Dalam pemrograman, tempat di memori komputer yang diberi nama dan berfungsi untuk menyimpan suatu nilai yang dapat berubah selama program berjalan disebut...",
        "options": [
            {"key": "A", "text": "Konstanta", "image_url": None, "match": None},
            {"key": "B", "text": "Variabel", "image_url": None, "match": None},
            {"key": "C", "text": "Fungsi", "image_url": None, "match": None},
            {"key": "D", "text": "Komentar", "image_url": None, "match": None},
            {"key": "E", "text": "Compiler", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Variabel adalah pengenal (identifier) memori yang memegang nilai data dinamis."
    },
    {
        "num": 44,
        "content": "Tipe data yang hanya dapat menyimpan dua kemungkinan nilai logika, yaitu Benar (True) atau Salah (False) adalah...",
        "options": [
            {"key": "A", "text": "Integer", "image_url": None, "match": None},
            {"key": "B", "text": "Float", "image_url": None, "match": None},
            {"key": "C", "text": "Boolean", "image_url": None, "match": None},
            {"key": "D", "text": "String", "image_url": None, "match": None},
            {"key": "E", "text": "Character", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "Boolean adalah tipe data biner logika yang bernilai True atau False."
    },
    {
        "num": 45,
        "content": "Dalam pemrograman Python, berapakah hasil dari operasi aritmetika berikut: 17 % 5 ?",
        "options": [
            {"key": "A", "text": "3", "image_url": None, "match": None},
            {"key": "B", "text": "2", "image_url": None, "match": None},
            {"key": "C", "text": "3.4", "image_url": None, "match": None},
            {"key": "D", "text": "1", "image_url": None, "match": None},
            {"key": "E", "text": "0", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Operator % adalah Modulo (sisa pembagian bulat): 17 dibagi 5 hasilnya 3 dengan sisa 2."
    },
    {
        "num": 46,
        "content": "Struktur perulangan (loop) yang paling tepat digunakan ketika pemrogram sudah mengetahui secara pasti berapa kali perulangan harus dieksekusi adalah...",
        "options": [
            {"key": "A", "text": "Perulangan FOR", "image_url": None, "match": None},
            {"key": "B", "text": "Perulangan WHILE tak hingga", "image_url": None, "match": None},
            {"key": "C", "text": "Struktur IF-ELSE", "image_url": None, "match": None},
            {"key": "D", "text": "Struktur SWITCH-CASE", "image_url": None, "match": None},
            {"key": "E", "text": "Fungsi Rekursif tanpa batas", "image_url": None, "match": None}
        ],
        "answer": "A",
        "explanation": "Perulangan 'for' (counted loop) digunakan saat jumlah iterasi sudah ditentukan di awal."
    },
    {
        "num": 47,
        "content": "Kesalahan penulisan aturan tata bahasa dalam kode pemrograman (seperti tanda kurung yang kurang atau salah ejaan kata kunci) sehingga program gagal dikompilasi disebut...",
        "options": [
            {"key": "A", "text": "Logical Error (Kesalahan Logika)", "image_url": None, "match": None},
            {"key": "B", "text": "Runtime Error", "image_url": None, "match": None},
            {"key": "C", "text": "Syntax Error (Kesalahan Sintaks)", "image_url": None, "match": None},
            {"key": "D", "text": "Hardware Failure", "image_url": None, "match": None},
            {"key": "E", "text": "Memory Leak", "image_url": None, "match": None}
        ],
        "answer": "C",
        "explanation": "Syntax error terjadi ketika aturan penulisan bahasa pemrograman dilanggar dan dicegah oleh interpreter/kompilator."
    },
    {
        "num": 48,
        "content": "Perangkat lunak yang kode sumbernya (source code) disediakan secara terbuka untuk umum sehingga siapapun bebas mempelajari, memodifikasi, dan menyebarluaskannya kembali disebut lisensi...",
        "options": [
            {"key": "A", "text": "Proprietary Software (Komersial Berpemilik)", "image_url": None, "match": None},
            {"key": "B", "text": "Open Source Software", "image_url": None, "match": None},
            {"key": "C", "text": "Shareware", "image_url": None, "match": None},
            {"key": "D", "text": "Adware", "image_url": None, "match": None},
            {"key": "E", "text": "Trialware", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "Open Source Software menyediakan kode sumber bebas untuk diteliti dan dikembangkan oleh komunitas."
    },
    {
        "num": 49,
        "content": "Kejahatan siber di mana pelaku mengirimkan tautan palsu melalui email atau pesan singkat yang menyerupai institusi resmi (seperti bank) untuk mengelabui korban agar memberikan password disebut...",
        "options": [
            {"key": "A", "text": "Phishing", "image_url": None, "match": None},
            {"key": "B", "text": "DDoS Attack", "image_url": None, "match": None},
            {"key": "C", "text": "Defacing", "image_url": None, "match": None},
            {"key": "D", "text": "Brute Force", "image_url": None, "match": None},
            {"key": "E", "text": "SQL Injection", "image_url": None, "match": None}
        ],
        "answer": "A",
        "explanation": "Phishing adalah upaya penipuan social engineering untuk memancing informasi rahasia kredensial akun."
    },
    {
        "num": 50,
        "content": "Metode keamanan akun yang mewajibkan pengguna memasukkan kode OTP (One-Time Password) dari SMS atau aplikasi authenticator selain password saat login disebut...",
        "options": [
            {"key": "A", "text": "Single Sign-On (SSO)", "image_url": None, "match": None},
            {"key": "B", "text": "Two-Factor Authentication (2FA)", "image_url": None, "match": None},
            {"key": "C", "text": "Biometric Bypass", "image_url": None, "match": None},
            {"key": "D", "text": "CAPTCHA Validation", "image_url": None, "match": None},
            {"key": "E", "text": "End-to-End Encryption", "image_url": None, "match": None}
        ],
        "answer": "B",
        "explanation": "2FA (Two-Factor Authentication) memberikan lapisan pertahanan kedua untuk memastikan identitas pengguna."
    }
]

def main():
    db = get_db()
    c = db.cursor()

    # 1. Cek apakah bank soal Informatika X sudah ada sebelumnya
    c.execute("SELECT id FROM cbt_question_banks WHERE subject_name = 'Informatika X' OR title LIKE '%Informatika X%'")
    row = c.fetchone()
    if row:
        bank_id = row[0]
        print(f"Menggunakan Bank Soal yang sudah ada (ID: {bank_id})")
        # Update info bank
        c.execute("""
            UPDATE cbt_question_banks 
            SET title = 'Bank Soal Informatika Kelas X (Uji Coba 50 Soal)',
                grade = 10,
                total_questions = 50,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (bank_id,))
        # Hapus soal lama dalam bank ini agar bersih
        c.execute("DELETE FROM cbt_questions WHERE bank_id = %s", (bank_id,))
    else:
        c.execute("""
            INSERT INTO cbt_question_banks (
                title, subject_name, grade, teacher_id, teacher_name, total_questions, origin, created_at, updated_at
            ) VALUES (
                'Bank Soal Informatika Kelas X (Uji Coba 50 Soal)',
                'Informatika X',
                10,
                15,
                'I Made Arya Adinata Dwija Putra',
                50,
                'official',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            ) RETURNING id
        """)
        bank_id = c.fetchone()[0]
        print(f"Bank Soal baru berhasil dibuat (ID: {bank_id})")

    # 2. Masukkan 50 soal
    inserted_count = 0
    for q in questions_data:
        options_json = json.dumps(q["options"], ensure_ascii=False)
        c.execute("""
            INSERT INTO cbt_questions (
                bank_id, question_number, question_type, content, options, correct_answer, points, explanation, created_at
            ) VALUES (
                %s, %s, 'multiple_choice', %s, %s, %s, 2.0, %s, CURRENT_TIMESTAMP
            )
        """, (bank_id, q["num"], q["content"], options_json, q["answer"], q["explanation"]))
        inserted_count += 1

    print(f"Berhasil memasukkan {inserted_count} butir soal ke Bank ID {bank_id}!")

    # 3. Hubungkan Bank Soal ke cbt_exam_subjects (Subject ID 11 Informatika X)
    c.execute("""
        UPDATE cbt_exam_subjects 
        SET bank_id = %s,
            total_questions = 50,
            status = 'ready',
            session_status = 'active'
        WHERE id = 11
    """, (bank_id,))
    print("Mata pelajaran Informatika X (Subject ID 11) telah dihubungkan ke Bank Soal ini dan diset aktif!")

    # 4. Reset sesi ujian untuk uji coba agar student 4 dapat langsung mengambil soal baru
    # Hapus jawaban lama dari sesi 12
    c.execute("DELETE FROM cbt_student_answers WHERE session_id = 12")
    c.execute("""
        UPDATE cbt_exam_sessions 
        SET status = 'in_progress',
            total_answered = 0,
            score = 0.0,
            lock_count = 0,
            lock_reason = NULL,
            device_id = NULL,
            ip_address = NULL,
            remaining_seconds = 90 * 60,
            start_time = CURRENT_TIMESTAMP,
            last_heartbeat = CURRENT_TIMESTAMP
        WHERE id = 12
    """)
    print("Sesi 12 (Mollie Fitzgerald) telah di-reset agar dapat mengerjakan 50 butir soal baru dengan durasi 90 menit!")

    db.commit()
    db.close()
    print("Semua proses selesai dengan sukses!")

if __name__ == "__main__":
    main()
