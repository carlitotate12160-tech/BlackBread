---
description: "Aturan untuk melakukan testing menggunakan server oracle."
always_on: true
---

# Aturan Testing (Oracle Server)

Setiap kali pengguna meminta untuk melakukan "testing" atau menjalankan pengujian, Anda **wajib** menggunakan server oracle. 

Gunakan urutan perintah berikut pada terminal/shell Anda:
1. Pastikan Anda berada di direktori proyek (`d:\BLACKBREAD` atau `/mnt/d/BLACKBREAD`).
2. `ssh oracle-blackbread` (atau `wsl ssh oracle-blackbread` jika menggunakan Windows).
3. `cd ~/blackbread`

Semua perintah testing (seperti menjalankan `make check`, integrasi, dsb.) harus dilakukan setelah berada di dalam direktori `~/blackbread` di server `oracle-blackbread`.
