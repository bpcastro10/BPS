"""Nombres y apellidos frecuentes en Ecuador, para corregir el beneficiario palabra por palabra.

Lista inicial armada a mano (no exhaustiva). Lo ideal es reemplazarla o ampliarla con los
beneficiarios reales de su base de clientes/proveedores: con una lista propia el acierto sube mucho.
"""

NOMBRES = """
Juan José Luis Carlos Jorge Miguel Manuel Pedro Francisco Antonio Javier Diego Daniel David Andrés
Fernando Ricardo Roberto Eduardo Sergio Pablo Mario Marco Marcos Víctor Raúl Héctor Óscar Alberto
Alejandro Santiago Sebastián Mateo Gabriel Rafael Ángel Fabián Patricio Germán Gustavo Hugo Iván Jaime
Julio César Leonardo Franklin Wilson Washington Édgar Edison Byron Klever Freddy Galo Hernán Ramiro
Rodrigo Rubén Segundo Silvio Vicente Xavier Cristian Christian Kevin Bryan Jhon John Darwin Dennis
Lenin Nelson Paúl Esteban Gonzalo Guillermo Enrique Ernesto Felipe Ignacio Joaquín Lucas Martín
Nicolás Samuel Tomás Emilio Álvaro Wilmer Walter Milton Marlon Stalin Jefferson Jonathan Ronald Richard
Henry Jairo Jhonny Holger Fausto Fredy Geovanny Giovanny Jimmy Johnny Kléber Lautaro Leonel Lisandro
Manuel Máximo Mauricio Medardo Moisés Néstor Orlando Patricio Remigio Renato Ronny Saúl Simón Teodoro
Ulises Wladimir Yandry Alex Alexander Andy Anthony Steven Steeven Josué Isaac Elías Ezequiel Gerardo
Agustín Benjamín Bolívar Camilo Ciro Darío Efraín Eloy Fidel Gilberto Gregorio Humberto Ismael Jacinto
María Ana Rosa Carmen Luz Martha Marta Gloria Patricia Mónica Sandra Verónica Andrea Daniela Gabriela
Paola Carolina Fernanda Valeria Camila Sofía Isabel Isabella Valentina Lucía Elena Laura Silvia
Alexandra Jessica Karina Katherine Lorena Mariana Natalia Paulina Raquel Ruth Sara Susana Teresa
Ximena Yolanda Cecilia Beatriz Blanca Inés Irene Julia Liliana Margarita Mercedes Nancy Norma Olga
Pilar Rocío Sonia Grace Emma Juana Esther Fátima Johanna Tatiana Viviana Rosario Ángeles Dolores
Guadalupe Mayra Erika Cristina Diana Marcela Amparo Narcisa Mariuxi Gissela Gisela Jenny Janeth Lourdes
Maribel Miriam Myriam Nelly Noemí Piedad Rebeca Rosana Shirley Vanessa Wendy Zoila Adriana Alicia
Amanda Ángela Antonella Aracely Bertha Claudia Doris Elizabeth Estefanía Evelyn Flor Germania Hilda
Ivonne Jacqueline Josefina Karla Kerly Leticia Lidia Lilia Luisa Magdalena Maritza Melissa Michelle
Nathaly Nataly Pamela Priscila Regina Roxana Selena Stefany Tania Vilma Virginia Yadira Zulay
""".split()

APELLIDOS = """
García Rodríguez González Fernández López Martínez Sánchez Pérez Gómez Martín Jiménez Ruiz Hernández
Díaz Moreno Muñoz Álvarez Romero Alonso Gutiérrez Navarro Torres Domínguez Vázquez Ramos Gil Ramírez
Serrano Blanco Suárez Molina Morales Ortega Delgado Castro Ortiz Rubio Marín Núñez Iglesias Medina
Garrido Cortés Castillo Santos Lozano Guerrero Cano Prieto Méndez Cruz Calvo Vidal León Márquez Herrera
Peña Flores Cabrera Campos Vega Fuentes Carrasco Caballero Reyes Nieto Aguilar Pascual Santana Herrero
Lorenzo Montero Hidalgo Giménez Ibáñez Ferrer Durán Santiago Benítez Mora Vicente Vargas Arias Carmona
Crespo Román Pastor Soto Velasco Moya Soler Parra Esteban Bravo Gallardo Rojas Zambrano Mendoza Vera
Cedeño Villacís Andrade Chávez Salazar Quishpe Guamán Paredes Bustamante Espinoza Espinosa Valencia
Rivera Zurita Sarmiento Velásquez Cevallos Ponce Intriago Macías Loor Mera Alvarado Toapanta Chicaiza
Tipán Pilco Yánez Jaramillo Carrión Montalvo Proaño Benavides Villavicencio Ordóñez Calderón Arteaga
Granda Vinueza Cueva Narváez Moreira Solórzano Palacios Figueroa Barreto Quiroz Burbano Aguirre
Mosquera Angulo Ojeda Regalado Aquino Estupiñán Contreras Mejía Rosero Pazmiño Erazo Guevara Tapia
Sandoval Cárdenas Bermeo Peralta Coronel Galarza Caicedo Lema Morocho Vélez Ruales Viteri Egas Terán
Pinto Silva Rosales Castañeda Escobar Acosta Acuña Albán Almeida Arcos Armijos Ayala Barrera Bastidas
Borja Cabezas Cajas Campoverde Cando Carvajal Castelo Cisneros Cobo Córdova Cornejo Cortez Cuenca
Chiriboga Dávila Enríquez Escudero Freire Gallegos Gavilanes Guzmán Haro Heredia Herdoíza Iza Játiva
Lara Larrea Llerena Lucero Maldonado Manosalvas Mantilla Mena Merino Miranda Montenegro Montesdeoca
Murillo Noboa Obando Olmedo Orellana Osorio Pacheco Padilla Palacios Pantoja Pérez Pillajo Quintana
Quinteros Recalde Reinoso Rengifo Robalino Robles Rocha Salas Salinas Samaniego Sanmartín Segovia
Sevilla Sosa Suquilanda Tamayo Tello Trujillo Ulloa Uquillas Valdivieso Valdez Valle Vallejo Vásconez
Vaca Villalba Villamar Villota Yépez Zamora Zapata Zúñiga Solís
""".split()

PARTICULAS = ["de", "del", "la", "las", "los", "y", "da", "san"]
